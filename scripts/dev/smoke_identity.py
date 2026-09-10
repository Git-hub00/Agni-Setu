"""Smoke-check the identity flow against a running local stack (demo mode only).

Exercises, through the nginx origin: CSRF bootstrap, OTP challenge, demo inbox code pickup,
verification (session cookie), /me, CSRF refusal without a token, and logout. Prints a compact
PASS/FAIL line per step and exits non-zero on the first failure. No secrets are printed; the
one-time code is read from the demo inbox and never echoed.

Usage:  uv run --directory backend python ../scripts/dev/smoke_identity.py [http://127.0.0.1:5173]
"""

from __future__ import annotations

import re
import sys

import requests

import time

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:5173"
# Unique synthetic contact per run: the per-contact hourly send limit (5) is a real control and
# repeated runs against one address would trip it (that refusal is itself correct behaviour).
CONTACT = f"smoke.{int(time.time())}@example.test"


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        sys.exit(1)


def main() -> None:
    s = requests.Session()
    r = s.get(f"{BASE}/api/v1/auth/csrf", timeout=10)
    token = r.json().get("data", {}).get("csrf_token", "")
    step("csrf bootstrap", r.status_code == 200 and bool(token) and "csrftoken" in s.cookies, f"[{r.status_code}]")

    r = s.post(
        f"{BASE}/api/v1/auth/otp/challenges",
        json={"channel": "EMAIL", "contact": CONTACT},
        timeout=10,
    )
    step("challenge WITHOUT token refused", r.status_code == 403 and r.json().get("code") == "CSRF_FAILED", f"[{r.status_code}]")

    headers = {"X-CSRFToken": token}
    r = s.post(
        f"{BASE}/api/v1/auth/otp/challenges",
        json={"channel": "EMAIL", "contact": CONTACT},
        headers=headers,
        timeout=10,
    )
    body = r.json().get("data", {})
    step("challenge created", r.status_code == 202 and "challenge_id" in body, f"[{r.status_code}] to {body.get('masked_destination')}")
    challenge_id = body["challenge_id"]

    r = s.get(f"{BASE}/api/v1/demo/inbox", params={"channel": "EMAIL", "contact": CONTACT}, timeout=10)
    messages = r.json().get("data", {}).get("messages", [])
    match = re.search(r"\b(\d{6})\b", messages[0]["body"]) if messages else None
    step("demo inbox delivered a code", r.status_code == 200 and match is not None, f"[{r.status_code}] messages={len(messages)}")
    code = match.group(1) if match else ""

    r = s.post(
        f"{BASE}/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "code": "000000", "channel": "EMAIL", "contact": CONTACT},
        headers=headers,
        timeout=10,
    )
    step("wrong code refused", r.status_code == 422 and r.json().get("code") == "OTP_INVALID", f"[{r.status_code}]")

    r = s.post(
        f"{BASE}/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "code": code, "channel": "EMAIL", "contact": CONTACT},
        headers=headers,
        timeout=10,
    )
    principal = r.json().get("data", {})
    step(
        "verify -> session",
        r.status_code == 200 and principal.get("kind") == "APPLICANT" and "sessionid" in s.cookies,
        f"[{r.status_code}] workspaces={principal.get('workspaces')}",
    )

    r = s.get(f"{BASE}/api/v1/me", timeout=10)
    step("/me with session", r.status_code == 200 and r.json()["data"]["id"] == principal["id"], f"[{r.status_code}]")

    # The CSRF token rotates at login (security s.2): the pre-login token must now be refused.
    r = s.post(
        f"{BASE}/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "code": code, "channel": "EMAIL", "contact": CONTACT},
        headers=headers,
        timeout=10,
    )
    step("stale pre-login CSRF token refused", r.status_code == 403, f"[{r.status_code}]")
    token = s.get(f"{BASE}/api/v1/auth/csrf", timeout=10).json()["data"]["csrf_token"]
    headers = {"X-CSRFToken": token}
    r = s.post(
        f"{BASE}/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "code": code, "channel": "EMAIL", "contact": CONTACT},
        headers=headers,
        timeout=10,
    )
    step("replayed (consumed) challenge refused", r.status_code == 422, f"[{r.status_code}]")

    r = s.post(f"{BASE}/api/v1/auth/logout", headers=headers, timeout=10)
    step("logout", r.status_code == 204, f"[{r.status_code}]")
    r = s.get(f"{BASE}/api/v1/me", timeout=10)
    step("/me after logout is anonymous", r.status_code == 401, f"[{r.status_code}]")
    print("ALL OTP SMOKE STEPS PASSED")

    if "--oidc" in sys.argv:
        oidc_phase()


def _env_file_value(key: str) -> str:
    """Read one value from the repository-root .env.local without printing it."""
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[2] / ".env.local"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def _keycloak_login(s: requests.Session, username: str, password: str) -> requests.Response:
    """Drive the browser flow: start -> Keycloak login form -> callback. Returns the final
    response after redirects (the callback's redirect target is followed)."""
    start = s.get(f"{BASE}/api/v1/auth/oidc/start", params={"next": "/account"}, timeout=15, allow_redirects=False)
    step("oidc start redirects to the identity provider", start.status_code == 302 and "/realms/agni-dev/protocol/openid-connect/auth" in start.headers.get("Location", ""), f"[{start.status_code}]")
    page = s.get(start.headers["Location"], timeout=15)
    form_action = re.search(r'action="([^"]+)"', page.text)
    step("identity provider login form", page.status_code == 200 and form_action is not None, f"[{page.status_code}]")
    action = form_action.group(1).replace("&amp;", "&") if form_action else ""
    # Keycloak 26 sets Secure cookies even over http. Browsers treat http://localhost as a secure
    # context and send them; Python's cookie jar does not, so mimic the browser for the local
    # provider only (never for the Agni Setu origin).
    for cookie in s.cookies:
        if cookie.domain.startswith("localhost"):
            cookie.secure = False
    return s.post(action, data={"username": username, "password": password, "credentialId": ""}, timeout=15, allow_redirects=True)


def oidc_phase() -> None:
    import subprocess

    kc = "http://localhost:8080"
    admin_user = _env_file_value("KC_BOOTSTRAP_ADMIN_USERNAME")
    admin_pass = _env_file_value("KC_BOOTSTRAP_ADMIN_PASSWORD")
    step("keycloak admin credentials available", bool(admin_user and admin_pass))

    # Unprovisioned staff identity: authenticates at the provider, refused by Agni Setu.
    s = requests.Session()
    final = _keycloak_login(s, "stranger", "demo-stranger-password")
    step("unprovisioned subject refused", final.url.endswith("/sign-in?error=forbidden") or "error=forbidden" in final.url, final.url)
    step("no session for unprovisioned subject", s.get(f"{BASE}/api/v1/me", timeout=10).status_code == 401)

    # Resolve chitra's stable subject id from the provider and provision the mapping.
    tok = requests.post(
        f"{kc}/realms/master/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli", "username": admin_user, "password": admin_pass},
        timeout=15,
    )
    step("keycloak admin token", tok.status_code == 200, f"[{tok.status_code}]")
    users = requests.get(
        f"{kc}/admin/realms/agni-dev/users",
        params={"username": "chitra", "exact": "true"},
        headers={"Authorization": f"Bearer {tok.json()['access_token']}"},
        timeout=15,
    )
    step("resolve chitra subject", users.status_code == 200 and len(users.json()) == 1, f"[{users.status_code}]")
    subject = users.json()[0]["id"]
    provision = subprocess.run(
        [
            "docker", "exec", "agni-dev-api-1", "python", "manage.py", "provision_demo_staff",
            "--issuer", "http://localhost:8080/realms/agni-dev", "--subject", subject,
            "--name", "Chitra Clerk", "--role", "SUPERVISOR", "--jurisdiction", "DEMO-CIRCLE-1",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    step("provision demo staff mapping", provision.returncode == 0, provision.stdout.strip().splitlines()[-1] if provision.stdout.strip() else provision.stderr.strip()[-200:])

    s = requests.Session()
    final = _keycloak_login(s, "chitra", "demo-chitra-password")
    step("provisioned subject signed in", "error=" not in final.url, final.url)
    me = s.get(f"{BASE}/api/v1/me", timeout=10)
    body = me.json().get("data", {})
    step("/me is the STAFF principal with the granted workspace", me.status_code == 200 and body.get("kind") == "STAFF" and body.get("workspaces") == ["supervisor"], f"[{me.status_code}] {body.get('workspaces')}")
    print("ALL OIDC SMOKE STEPS PASSED")


if __name__ == "__main__":
    main()
