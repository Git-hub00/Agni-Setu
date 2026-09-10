"""Smoke-check B04 (premises, applicability, policy governance) against a running local stack.

Runs after `seed_demo --scenario baseline` (demo mode only). Through the nginx origin:
applicant OTP sign-in as the seeded persona, service catalogue, nonbinding applicability preview,
premises list/create/replay/precondition checks, and the applicant's refusal from the policy
workspace. With `--oidc`, Meera (policy approver) signs in through the real Keycloak and reads the
active policy; a command against an ACTIVE version is refused as an invalid transition.
Prints PASS/FAIL per step, exits non-zero on the first failure, never echoes codes or secrets.

Usage:  uv run --directory backend python ../scripts/dev/smoke_policy.py [http://127.0.0.1:5173] [--oidc]
"""

from __future__ import annotations

import re
import sys
import uuid

import requests

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:5173").rstrip("/")
CONTACT = "rakesh@example.test"  # seeded synthetic applicant (docs/13 persona p1)


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        sys.exit(1)


def sign_in_applicant() -> tuple[requests.Session, dict[str, str]]:
    s = requests.Session()
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=10).json()["data"]["csrf_token"]
    headers = {"X-CSRFToken": token}
    r = s.post(f"{BASE}/api/v1/auth/otp/challenges", json={"channel": "EMAIL", "contact": CONTACT}, headers=headers, timeout=10)
    step("otp challenge for seeded applicant", r.status_code == 202, f"[{r.status_code}]")
    challenge_id = r.json()["data"]["challenge_id"]
    inbox = s.get(f"{BASE}/api/v1/demo/inbox", params={"channel": "EMAIL", "contact": CONTACT}, timeout=10)
    messages = inbox.json().get("data", {}).get("messages", [])
    match = re.search(r"\b(\d{6})\b", messages[0]["body"]) if messages else None
    step("demo inbox delivered a code", inbox.status_code == 200 and match is not None, f"[{inbox.status_code}]")
    r = s.post(
        f"{BASE}/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "code": match.group(1) if match else "", "channel": "EMAIL", "contact": CONTACT},
        headers=headers,
        timeout=10,
    )
    me = r.json().get("data", {})
    step("verify -> seeded principal Rakesh Mehta", r.status_code == 200 and me.get("display_name") == "Rakesh Mehta", f"[{r.status_code}] {me.get('display_name')}")
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=10).json()["data"]["csrf_token"]
    return s, {"X-CSRFToken": token}


def applicant_phase() -> None:
    public = requests.get(f"{BASE}/api/v1/services", params={"category_key": "Hospital"}, timeout=10)
    items = public.json().get("data", {}).get("items", [])
    service = next((i for i in items if i["key"] == "demo-fire-noc"), None)
    step("public catalogue lists demo-fire-noc as available", public.status_code == 200 and service is not None and service["available"], f"[{public.status_code}] {service and service['explanation']}")
    assert service is not None

    s, headers = sign_in_applicant()
    r = s.post(f"{BASE}/api/v1/services/{service['service_id']}/applicability", json={"declared_category": "Hospital"}, headers=headers, timeout=10)
    body = r.json().get("data", {})
    step(
        "applicability preview: Hospital needs evacuation plan, nonbinding",
        r.status_code == 200 and body.get("applicable") is True and body.get("required_documents") == ["ownership", "plan", "electrical", "evacuation"] and body.get("binding") is False,
        f"[{r.status_code}] docs={body.get('required_documents')} policy=v{body.get('policy_number')}",
    )
    r = s.post(f"{BASE}/api/v1/services/{service['service_id']}/applicability", json={"declared_category": "Nightclub"}, headers=headers, timeout=10)
    body = r.json().get("data", {})
    step("unknown category -> uncertainty, no invented documents", r.status_code == 200 and body.get("applicable") is False and body.get("required_documents") == [], f"[{r.status_code}]")

    r = s.get(f"{BASE}/api/v1/premises", timeout=10)
    names = sorted(p["display_name"] for p in r.json().get("data", {}).get("items", []))
    step("seeded premises visible to their owner only", r.status_code == 200 and "Mehta Family Restaurant" in names, f"[{r.status_code}] {len(names)} premises")

    key = str(uuid.uuid4())
    payload = {
        "display_name": f"Smoke Premises {key[:8]}",
        "address_line1": "12 Market Street (synthetic)",
        "locality": "Patel Nagar",
        "ward_key": "W-06",
        "postal_code": "110008",
        "category_key": "Restaurant",
        "area_sqm": "150.00",
        "height_m": "5.00",
        "floor_count": 1,
    }
    r = s.post(f"{BASE}/api/v1/premises", json=payload, headers={**headers, "Idempotency-Key": key}, timeout=10)
    step("register premises (command with idempotency key)", r.status_code == 201 and r.json()["data"]["replayed"] is False, f"[{r.status_code}] ETag={r.headers.get('ETag')}")
    premises_id = r.json()["data"]["premises_id"]
    etag = r.headers.get("ETag", "")
    r2 = s.post(f"{BASE}/api/v1/premises", json=payload, headers={**headers, "Idempotency-Key": key}, timeout=10)
    step("same key + same payload -> replayed receipt", r2.status_code == 201 and r2.json()["data"]["replayed"] is True and r2.json()["data"]["premises_id"] == premises_id, f"[{r2.status_code}]")
    r3 = s.post(f"{BASE}/api/v1/premises", json={**payload, "display_name": "Different"}, headers={**headers, "Idempotency-Key": key}, timeout=10)
    step("same key + different payload -> IDEMPOTENCY_CONFLICT", r3.status_code == 409 and r3.json().get("code") == "IDEMPOTENCY_CONFLICT", f"[{r3.status_code}]")
    r4 = s.patch(f"{BASE}/api/v1/premises/{premises_id}", json={"display_name": "Renamed"}, headers={**headers, "Idempotency-Key": str(uuid.uuid4())}, timeout=10)
    step("edit without If-Match -> 428", r4.status_code == 428, f"[{r4.status_code}]")
    r5 = s.patch(f"{BASE}/api/v1/premises/{premises_id}", json={"display_name": "Renamed by smoke"}, headers={**headers, "Idempotency-Key": str(uuid.uuid4()), "If-Match": etag}, timeout=10)
    step("edit with current ETag -> 200, version bumped", r5.status_code == 200 and r5.headers.get("ETag", "").endswith(":v2\"'".strip("'")), f"[{r5.status_code}] ETag={r5.headers.get('ETag')}")
    r6 = s.patch(f"{BASE}/api/v1/premises/{premises_id}", json={"display_name": "Stale"}, headers={**headers, "Idempotency-Key": str(uuid.uuid4()), "If-Match": etag}, timeout=10)
    step("edit with stale ETag -> 412 VERSION_CONFLICT", r6.status_code == 412 and r6.json().get("code") == "VERSION_CONFLICT", f"[{r6.status_code}]")

    r = s.get(f"{BASE}/api/v1/policies", timeout=10)
    step("applicant refused from the policy workspace", r.status_code == 403, f"[{r.status_code}]")
    r = s.get(f"{BASE}/api/v1/delegations", timeout=10)
    step("delegations list scoped to the applicant", r.status_code == 200, f"[{r.status_code}] items={len(r.json().get('data', {}).get('items', []))}")
    s.post(f"{BASE}/api/v1/auth/logout", headers=headers, timeout=10)
    print("ALL APPLICANT SMOKE STEPS PASSED")


def _keycloak_login(s: requests.Session, username: str, password: str) -> requests.Response:
    start = s.get(f"{BASE}/api/v1/auth/oidc/start", params={"next": "/policy"}, timeout=60, allow_redirects=False)
    step("oidc start redirects to the identity provider", start.status_code == 302, f"[{start.status_code}]")
    page = s.get(start.headers["Location"], timeout=60)
    form_action = re.search(r'action="([^"]+)"', page.text)
    step("identity provider login form", page.status_code == 200 and form_action is not None, f"[{page.status_code}]")
    action = form_action.group(1).replace("&amp;", "&") if form_action else ""
    for cookie in s.cookies:  # browsers treat http://localhost as secure; Python's jar does not
        if cookie.domain.startswith("localhost"):
            cookie.secure = False
    return s.post(action, data={"username": username, "password": password, "credentialId": ""}, timeout=60, allow_redirects=True)


def staff_phase() -> None:
    s = requests.Session()
    final = _keycloak_login(s, "meera", "demo-meera-password")
    step("meera (fixed Keycloak id) signed in via seeded mapping", "error=" not in final.url, final.url)
    me = s.get(f"{BASE}/api/v1/me", timeout=10).json().get("data", {})
    step("/me STAFF with policy workspace", me.get("kind") == "STAFF" and "policy" in me.get("workspaces", []), f"{me.get('display_name')} {me.get('workspaces')}")
    r = s.get(f"{BASE}/api/v1/policies", timeout=10)
    items = r.json().get("data", {}).get("items", [])
    active = next((i for i in items if i["state"] == "ACTIVE"), None)
    step("policy list shows the seeded ACTIVE version", r.status_code == 200 and active is not None, f"[{r.status_code}] versions={len(items)}")
    assert active is not None
    d = s.get(f"{BASE}/api/v1/policies/{active['policy_version_id']}", timeout=10)
    detail = d.json().get("data", {})
    approve_hint = next((a for a in detail.get("allowed_actions", []) if a["key"] == "approve"), {})
    step(
        "detail: contributors + passed simulation + approve not allowed on ACTIVE",
        d.status_code == 200 and len(detail.get("contributors", [])) >= 1 and any(x["passed"] for x in detail.get("simulations", [])) and approve_hint.get("enabled") is False,
        f"[{d.status_code}] ETag={d.headers.get('ETag')}",
    )
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=10).json()["data"]["csrf_token"]
    r = s.post(
        f"{BASE}/api/v1/policies/{active['policy_version_id']}/approve",
        json={"candidate_sha256": detail["payload_sha256"], "effective_from": "2027-01-01T00:00:00Z", "reason": "smoke: must be refused on an ACTIVE version"},
        headers={"X-CSRFToken": token, "Idempotency-Key": str(uuid.uuid4()), "If-Match": d.headers.get("ETag", "")},
        timeout=10,
    )
    step("approve on ACTIVE version refused (INVALID_TRANSITION)", r.status_code == 409 and r.json().get("code") == "INVALID_TRANSITION", f"[{r.status_code}] {r.json().get('code')}")
    print("ALL STAFF SMOKE STEPS PASSED")


if __name__ == "__main__":
    # `--staff-only` skips the applicant phase (the seeded contact has a real 5/hour OTP limit).
    if "--staff-only" not in sys.argv:
        applicant_phase()
    if "--oidc" in sys.argv or "--staff-only" in sys.argv:
        staff_phase()
