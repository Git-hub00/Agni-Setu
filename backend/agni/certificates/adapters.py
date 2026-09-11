"""Renderer / signer / verifier adapters (integrations s.5-7).

`demo_watermark` is the only signing arrangement of the demonstration build: the receipt binds a
watermark statement to the artifact hash and says in words that it is NOT a digital signature.
No adapter here produces, or claims, a real government signature; a live signer arrives only
through the same port with an approved arrangement (docs/19)."""

from __future__ import annotations

import base64
import hashlib
import html
import io
from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar

from django.conf import settings

from agni.platform.errors import DependencyUnavailable

from .ports import (
    RenderedArtifact,
    RendererFailed,
    RendererUnavailable,
    SignerRejected,
    SignerUnavailable,
    SignerUnknownOutcome,
    SignLookup,
    SignReceipt,
    VerificationResult,
)

DEMO_ISSUER = "Agni Setu demonstration issuer (synthetic; not a government authority)"
WATERMARK = "DEMONSTRATION - NOT AN OFFICIAL CERTIFICATE"
MODE_DEMO_WATERMARK = "DEMO_WATERMARK"


# ---- rendering ---------------------------------------------------------------------------------


def minimal_pdf(lines: list[str]) -> bytes:
    """A small, valid single-page PDF (Helvetica text lines). Used by the simulated renderer so
    hermetic tests and hosts without Pango still produce a real PDF structure."""

    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 13 Tf", "16 TL", "48 790 Td"]
    for line in lines:
        ops.append(f"({esc(line)}) Tj T*")
    ops.append("ET")
    content = "\n".join(ops).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def _lines(snapshot: Mapping[str, Any]) -> list[str]:
    return [
        WATERMARK,
        f"Demonstration fire safety certificate {snapshot.get('certificate_number', '')}",
        f"Premises: {snapshot.get('premises_display_name', '')}, {snapshot.get('locality', '')}",
        f"Category: {snapshot.get('category_key', '')}",
        f"Case reference: {snapshot.get('public_reference', '')}",
        f"Issued: {snapshot.get('issued_at', '')}",
        f"Valid until: {snapshot.get('valid_until', '')}",
        f"Issuer: {snapshot.get('issuer', DEMO_ISSUER)}",
        f"Verify at: {snapshot.get('verification_url', '')}",
        "Sample scope: synthetic demonstration data; no legal effect.",
    ]


class SimulatedRenderer:
    """Hermetic renderer: deterministic PDF bytes for the same snapshot."""

    name = "simulated"
    version = "1"

    def render(
        self, template_key: str, template_version: int, snapshot: Mapping[str, Any]
    ) -> RenderedArtifact:
        data = minimal_pdf([*_lines(snapshot), f"Template {template_key} v{template_version}"])
        return RenderedArtifact(
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
            media_type="application/pdf",
            renderer=self.name,
            renderer_version=self.version,
            mode=MODE_DEMO_WATERMARK,
        )


def qr_data_uri(text: str) -> str:
    import qrcode

    image = qrcode.make(text)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def render_html(template_key: str, template_version: int, snapshot: Mapping[str, Any]) -> str:
    def cell(key: str) -> str:
        return html.escape(str(snapshot.get(key, "")))

    verification_url = str(snapshot.get("verification_url", ""))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{cell("certificate_number")}</title>
<style>
  @page {{ size: A4; margin: 18mm; }}
  body {{ font-family: 'DejaVu Sans', sans-serif; color: #1f1f1f; position: relative; }}
  .watermark {{ position: fixed; top: 40%; left: 0; right: 0; text-align: center;
    font-size: 34pt; font-weight: 700; color: rgba(190, 30, 30, 0.28);
    transform: rotate(-24deg); letter-spacing: 2px; }}
  h1 {{ font-size: 20pt; margin: 0 0 4mm; }}
  .banner {{ border: 2px solid #8b1e1e; color: #8b1e1e; padding: 3mm; font-weight: 700;
    text-align: center; margin-bottom: 8mm; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 11pt; }}
  td {{ padding: 2.2mm 2mm; border-bottom: 1px solid #ddd; vertical-align: top; }}
  td.k {{ width: 34%; color: #555; }}
  .qr {{ margin-top: 8mm; }}
  .fine {{ font-size: 9pt; color: #555; margin-top: 8mm; }}
</style></head><body>
<div class="watermark">{html.escape(WATERMARK)}</div>
<div class="banner">{html.escape(WATERMARK)}</div>
<h1>Demonstration fire safety certificate</h1>
<table>
  <tr><td class="k">Certificate number</td><td>{cell("certificate_number")}</td></tr>
  <tr><td class="k">Premises</td><td>{cell("premises_display_name")}, {cell("locality")}</td></tr>
  <tr><td class="k">Category</td><td>{cell("category_key")}</td></tr>
  <tr><td class="k">Case reference</td><td>{cell("public_reference")}</td></tr>
  <tr><td class="k">Issued</td><td>{cell("issued_at")}</td></tr>
  <tr><td class="k">Valid until</td><td>{cell("valid_until")}</td></tr>
  <tr><td class="k">Issuer</td><td>{cell("issuer")}</td></tr>
  <tr><td class="k">Sample scope</td><td>Synthetic demonstration data; no legal effect.</td></tr>
  <tr><td class="k">Template</td><td>{html.escape(template_key)} v{template_version}</td></tr>
</table>
<div class="qr"><img alt="Verification QR code" width="120" height="120"
  src="{qr_data_uri(verification_url)}"><div>{html.escape(verification_url)}</div></div>
<p class="fine">Mode: {cell("mode")}. This sample carries a watermark statement bound to the
document hash; it is not a digital signature and confers no authorisation.</p>
</body></html>"""


class WeasyPrintRenderer:
    """Real PDF rendering (WeasyPrint 70; Pango/Cairo present in the Linux api image)."""

    name = "weasyprint"

    def render(
        self, template_key: str, template_version: int, snapshot: Mapping[str, Any]
    ) -> RenderedArtifact:
        try:
            import weasyprint
        except Exception as exc:  # noqa: BLE001 - missing native libraries on this host
            raise RendererUnavailable(f"WeasyPrint is not available here: {exc}") from exc
        markup = render_html(template_key, template_version, snapshot)
        try:
            data = weasyprint.HTML(string=markup).write_pdf()
        except Exception as exc:  # noqa: BLE001 - rendering error for this input
            raise RendererFailed(str(exc)[:200]) from exc
        if not isinstance(data, bytes) or not data.startswith(b"%PDF"):
            raise RendererFailed("renderer returned no PDF bytes")
        return RenderedArtifact(
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
            media_type="application/pdf",
            renderer=self.name,
            renderer_version=str(getattr(weasyprint, "__version__", "unknown")),
            mode=MODE_DEMO_WATERMARK,
        )


# ---- signing ------------------------------------------------------------------------------------


class DemoWatermarkSigner:
    """Demo 'signing' = a watermark statement bound to the artifact hash (NOT a digital
    signature). Class-level hooks let tests drive the docs/16 s.6 outcomes: unavailable (never
    reached), unknown (reached, no answer), rejected, and lookup states."""

    name = "demo_watermark"
    mode = MODE_DEMO_WATERMARK
    force_outcome: ClassVar[str | None] = None  # None | unavailable | unknown | rejected
    lookup_override: ClassVar[str | None] = None  # None | NOT_FOUND | UNKNOWN
    _submitted: ClassVar[dict[str, SignReceipt]] = {}

    @classmethod
    def reset(cls) -> None:
        cls.force_outcome = None
        cls.lookup_override = None
        cls._submitted.clear()

    def submit(self, stable_request_id: str, artifact_sha256: str, *, at: datetime) -> SignReceipt:
        forced = type(self).force_outcome
        if forced == "unavailable":
            raise SignerUnavailable("demo signer unreachable (forced outage)")
        if forced == "rejected":
            raise SignerRejected("demo signer refused the artifact (forced)")
        receipt = SignReceipt(
            provider=self.name,
            request_id=stable_request_id,
            artifact_sha256=artifact_sha256,
            signed_at=at,
            mode=self.mode,
            evidence={
                "statement": (
                    "Demonstration watermark bound to the artifact hash; not a digital signature"
                ),
                "artifact_sha256": artifact_sha256,
            },
        )
        type(self)._submitted[stable_request_id] = receipt  # the request reached the signer
        if forced == "unknown":
            raise SignerUnknownOutcome("timeout after the request reached the signer (forced)")
        return receipt

    def lookup(self, stable_request_id: str) -> SignLookup:
        override = type(self).lookup_override
        if override == "UNKNOWN":
            return SignLookup("UNKNOWN")
        if override == "NOT_FOUND":
            return SignLookup("NOT_FOUND")
        receipt = type(self)._submitted.get(stable_request_id)
        return SignLookup("COMPLETED", receipt) if receipt else SignLookup("NOT_FOUND")


class DemoSignatureVerifier:
    """Verifies the demo receipt against the stored artifact hash. Retained evidence states the
    method; no cryptographic signature is claimed."""

    name = "demo_hash_match"

    def verify(
        self, artifact_sha256: str, receipt: SignReceipt, *, expected_issuer: str
    ) -> VerificationResult:
        valid = (
            receipt.artifact_sha256 == artifact_sha256
            and receipt.provider == DemoWatermarkSigner.name
            and receipt.mode == MODE_DEMO_WATERMARK
        )
        return VerificationResult(
            valid=valid,
            evidence={
                "method": self.name,
                "expected_issuer": expected_issuer,
                "provider": receipt.provider,
                "artifact_sha256": artifact_sha256,
                "note": "Demo watermark receipt; not a cryptographic signature verification",
            },
        )


# ---- resolution --------------------------------------------------------------------------------


def get_renderer() -> SimulatedRenderer | WeasyPrintRenderer:
    provider = settings.CERTIFICATE_RENDERER_PROVIDER
    if provider == "weasyprint":
        return WeasyPrintRenderer()
    if provider == "simulated":
        return SimulatedRenderer()
    raise DependencyUnavailable(f"Certificate renderer '{provider}' has no adapter installed")


def get_signer() -> DemoWatermarkSigner:
    provider = settings.SIGNING_PROVIDER
    if provider == "demo_watermark":
        return DemoWatermarkSigner()
    raise DependencyUnavailable(f"Signing provider '{provider}' has no adapter installed")


def get_verifier() -> DemoSignatureVerifier:
    provider = settings.SIGNING_PROVIDER
    if provider == "demo_watermark":
        return DemoSignatureVerifier()
    raise DependencyUnavailable(f"Signature verifier for '{provider}' is not installed")
