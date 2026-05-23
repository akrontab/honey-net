"""
Metadata extractor — watches the shared inbox for new malware samples and writes
{sha256}.meta.json sidecars consumed by malware-sender.

Honeypots drop downloaded binaries into the inbox named by their SHA-256 digest.
This service detects new arrivals, verifies each file's hash, identifies the file
type from magic bytes, and writes a sidecar without touching any log format.

Configured via env vars:
  INBOX_DIR   Directory to watch for new samples (default /inbox)
  POLL_SECS   How often to scan for new files (default 2)
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

INBOX_DIR = Path(os.getenv("INBOX_DIR", "/inbox"))
POLL_SECS = int(os.getenv("POLL_SECS", "2"))

_SHA256_CHARS = frozenset("0123456789abcdef")

_MAGIC_TYPES: list[tuple[bytes, str]] = [
    (b"\x7fELF",           "elf"),
    (b"MZ",                "pe"),
    (b"\xca\xfe\xba\xbe", "macho"),
    (b"\xce\xfa\xed\xfe", "macho"),
    (b"\xcf\xfa\xed\xfe", "macho"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sha256_name(name: str) -> bool:
    return len(name) == 64 and all(c in _SHA256_CHARS for c in name)


def _filetype(header: bytes) -> str:
    for magic, label in _MAGIC_TYPES:
        if header[: len(magic)] == magic:
            return label
    return "data"


def _read_file(path: Path) -> tuple[bytes, str, int]:
    """Return (first 4 bytes, sha256 hex, file size) in one pass."""
    h = hashlib.sha256()
    header = b""
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            if not header:
                header = chunk[:4]
            h.update(chunk)
            size += len(chunk)
    return header, h.hexdigest(), size


def _write_sidecar(path: Path) -> None:
    sha256  = path.name
    sidecar = INBOX_DIR / f"{sha256}.meta.json"
    if sidecar.exists():
        return

    header, actual, size = _read_file(path)
    if actual != sha256:
        return  # file still being written — retry next poll

    ftype = _filetype(header)
    sidecar.write_text(
        json.dumps({
            "sha256":    sha256,
            "size":      size,
            "filetype":  ftype,
            "timestamp": _now(),
        }),
        encoding="utf-8",
    )
    print(f"[{_now()}] sidecar  {sha256[:12]}  size={size}  type={ftype}", flush=True)


def main() -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{_now()}] metadata extractor started  inbox={INBOX_DIR}", flush=True)

    while True:
        for path in INBOX_DIR.iterdir():
            if not path.is_file() or not _is_sha256_name(path.name):
                continue
            try:
                _write_sidecar(path)
            except OSError as exc:
                print(f"[{_now()}] skip {path.name[:12]}: {exc}", flush=True)
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
