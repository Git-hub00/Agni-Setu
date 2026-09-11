"""Scanner adapters: the demo scanner's verdicts and the clamd INSTREAM client against a local
fake clamd (real socket protocol), including outage -> UNKNOWN."""

from __future__ import annotations

import socket
import struct
import threading
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from agni.documents.adapters.scanners import EICAR_MARKER, ClamdScanner, DemoEicarScanner

NOW = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


def test_demo_scanner_rejects_eicar_even_across_chunks() -> None:
    scanner = DemoEicarScanner()
    marker = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + EICAR_MARKER + b"!$H+H*"
    split = len(marker) // 2
    assert scanner.scan([marker[:split], marker[split:]], at=NOW).verdict == "REJECTED"
    assert scanner.scan([b"%PDF-1.7 clean"], at=NOW).verdict == "CLEAN"
    DemoEicarScanner.force_unknown = True
    try:
        assert scanner.scan([b"anything"], at=NOW).verdict == "UNKNOWN"
    finally:
        DemoEicarScanner.force_unknown = False


class FakeClamd:
    """Minimal clamd: answers VERSION and INSTREAM; FOUND when the EICAR marker is present."""

    def __init__(self, *, reply_error: bool = False) -> None:
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        self.reply_error = reply_error
        self.received: list[bytes] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        for _ in range(4):
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                command = b""
                while not command.endswith(b"\0"):  # byte-wise: never swallow the first frame
                    command += _recv_exact(conn, 1)
                if command == b"zVERSION\0":
                    conn.sendall(b"ClamAV 1.5.4/27000/Wed Sep 10 2026\0")
                    continue
                payload = bytearray()
                while True:
                    header = _recv_exact(conn, 4)
                    (length,) = struct.unpack("!I", header)
                    if length == 0:
                        break
                    payload.extend(_recv_exact(conn, length))
                self.received.append(bytes(payload))
                if self.reply_error:
                    conn.sendall(b"INSTREAM size limit exceeded. ERROR\0")
                elif EICAR_MARKER in payload:
                    conn.sendall(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
                else:
                    conn.sendall(b"stream: OK\0")

    def close(self) -> None:
        self.server.close()


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError("peer closed")
        data += chunk
    return data


@pytest.fixture
def fake_clamd() -> Iterator[FakeClamd]:
    server = FakeClamd()
    yield server
    server.close()


def test_clamd_client_clean_and_found(fake_clamd: FakeClamd) -> None:
    scanner = ClamdScanner("127.0.0.1", fake_clamd.port, connect_timeout=2, read_timeout=2)
    clean = scanner.scan([b"%PDF-1.7 ", b"harmless bytes" * 10], at=NOW)
    assert clean.verdict == "CLEAN" and clean.engine == "clamav"
    assert clean.engine_version.startswith("ClamAV 1.5.4")
    assert fake_clamd.received[0] == b"%PDF-1.7 " + b"harmless bytes" * 10  # framed correctly
    found = scanner.scan([b"X" + EICAR_MARKER + b"Y"], at=NOW)
    assert found.verdict == "REJECTED" and found.detail == "Win.Test.EICAR_HDB-1"


def test_clamd_client_error_and_outage_are_unknown() -> None:
    erroring = FakeClamd(reply_error=True)
    try:
        result = ClamdScanner("127.0.0.1", erroring.port, connect_timeout=2, read_timeout=2).scan(
            [b"x"], at=NOW
        )
        assert result.verdict == "UNKNOWN" and "ERROR" in result.detail
    finally:
        erroring.close()
    # Nothing listening: connection refused -> UNKNOWN, never CLEAN.
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()
    outage = ClamdScanner("127.0.0.1", free_port, connect_timeout=1, read_timeout=1).scan(
        [b"x"], at=NOW
    )
    assert outage.verdict == "UNKNOWN" and "unavailable" in outage.detail
