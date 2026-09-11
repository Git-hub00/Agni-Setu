"""Malware scanner adapters. `ClamdScanner` streams bytes to clamd with the INSTREAM protocol
(bounded connect/read timeouts); any outage, timeout or protocol error is UNKNOWN - never CLEAN.
`DemoEicarScanner` is the local test scanner: it rejects the EICAR test signature and can be
forced into an outage for recovery tests."""

from __future__ import annotations

import socket
import struct
from collections.abc import Iterable
from datetime import datetime

from ..ports import ScanResult

EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
CLEAN, REJECTED, UNKNOWN = "CLEAN", "REJECTED", "UNKNOWN"


class DemoEicarScanner:
    name = "demo_eicar"
    force_unknown = False  # test hook (class-level so a monkeypatch reaches every instance)

    def scan(self, chunks: Iterable[bytes], *, at: datetime) -> ScanResult:
        if type(self).force_unknown:
            return ScanResult(UNKNOWN, self.name, "demo", "scanner outage (forced)", at)
        tail = b""
        found = False
        for chunk in chunks:
            window = tail + chunk
            if EICAR_MARKER in window:
                found = True
            tail = window[-len(EICAR_MARKER) :]
        if found:
            return ScanResult(REJECTED, self.name, "demo", "Eicar-Test-Signature", at)
        return ScanResult(CLEAN, self.name, "demo", "OK", at)


class ClamdScanner:
    """clamd INSTREAM client (docs/08 defaults: 5 s connect, 30 s request)."""

    name = "clamav"

    def __init__(
        self, host: str, port: int, *, connect_timeout: float = 5.0, read_timeout: float = 30.0
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    def _version(self) -> str:
        try:
            with socket.create_connection(
                (self._host, self._port), timeout=self._connect_timeout
            ) as sock:
                sock.settimeout(self._read_timeout)
                sock.sendall(b"zVERSION\0")
                return _recv_all(sock).rstrip(b"\0").decode("utf-8", "replace")[:120]
        except OSError:
            return "unknown"

    def scan(self, chunks: Iterable[bytes], *, at: datetime) -> ScanResult:
        try:
            with socket.create_connection(
                (self._host, self._port), timeout=self._connect_timeout
            ) as sock:
                sock.settimeout(self._read_timeout)
                sock.sendall(b"zINSTREAM\0")
                for chunk in chunks:
                    for start in range(0, len(chunk), 65536):
                        piece = chunk[start : start + 65536]
                        sock.sendall(struct.pack("!I", len(piece)) + piece)
                sock.sendall(struct.pack("!I", 0))
                reply = _recv_all(sock).rstrip(b"\0").decode("utf-8", "replace")
        except OSError as exc:
            return ScanResult(
                UNKNOWN, self.name, "unknown", f"scanner unavailable: {type(exc).__name__}", at
            )
        version = self._version()
        if reply.endswith("OK"):
            return ScanResult(CLEAN, self.name, version, "OK", at)
        if reply.endswith("FOUND"):
            signature = reply.split(":", 1)[-1].strip().removesuffix("FOUND").strip()
            return ScanResult(REJECTED, self.name, version, signature[:200], at)
        # ERROR (e.g. size limit exceeded, parser failure) or an unexpected reply: unresolved.
        return ScanResult(UNKNOWN, self.name, version, reply[:200] or "empty reply", at)


def _recv_all(sock: socket.socket) -> bytes:
    parts: list[bytes] = []
    while True:
        data = sock.recv(4096)
        if not data:
            break
        parts.append(data)
        if data.endswith(b"\0"):
            break
    return b"".join(parts)
