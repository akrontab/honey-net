"""
Metadata extractor — canonicalises and enriches malware samples dropped by
honeypots into per-honeypot subdirs of the shared inbox.

Each honeypot drops binaries into /inbox/<honeypot>/ with whatever filename
the upstream code happens to choose. This service:

  1. Walks /inbox/*/ for binary files
  2. Skips files still being written (mtime stability)
  3. Reads any co-located <name>.capture.json sidecar dropped by the honeypot
     containing {src_ip, url, session_id, captured_at}
  4. SHA-256 hashes the binary
  5. Moves it to /inbox/<sha256>
  6. Writes /inbox/<sha256>.meta.json merging derived + captured fields
  7. Deletes the original capture sidecar

Provenance fields (src_ip, url, session_id) are populated only when a capture
sidecar exists. honeypot and original_name are always derivable from the path.

Configured via env vars:
  INBOX_DIR          Root inbox dir (default /inbox)
  POLL_SECS          Scan interval (default 2)
  MTIME_SETTLE_SECS  How long after last write before processing (default 5)
"""

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

INBOX_DIR         = Path(os.getenv("INBOX_DIR", "/inbox"))
POLL_SECS         = int(os.getenv("POLL_SECS", "2"))
MTIME_SETTLE_SECS = int(os.getenv("MTIME_SETTLE_SECS", "5"))

_MAGIC_TYPES: list[tuple[bytes, str]] = [
    (b"\x7fELF",          "elf"),
    (b"MZ",               "pe"),
    (b"\xca\xfe\xba\xbe", "macho"),
    (b"\xce\xfa\xed\xfe", "macho"),
    (b"\xcf\xfa\xed\xfe", "macho"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _filetype(header: bytes) -> str:
    for magic, label in _MAGIC_TYPES:
        if header[: len(magic)] == magic:
            return label
    return "data"


def _hash_file(path: Path) -> tuple[bytes, str, int]:
    """Return (first 4 bytes, sha256 hex, size) in one pass."""
    h = hashlib.sha256()
    header = b""
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            if not header:
                header = chunk[: 4]
            h.update(chunk)
            size += len(chunk)
    return header, h.hexdigest(), size


def _capture_path(binary: Path) -> Path:
    return binary.parent / f"{binary.name}.capture.json"


def _load_capture(binary: Path) -> dict:
    path = _capture_path(binary)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _process(binary: Path, honeypot: str) -> None:
    if time.time() - binary.stat().st_mtime < MTIME_SETTLE_SECS:
        return  # still being written

    capture      = _load_capture(binary)
    captured_at  = capture.get("captured_at") or _iso_mtime(binary)
    original     = binary.name

    header, sha256, size = _hash_file(binary)

    canonical = INBOX_DIR / sha256
    sidecar   = INBOX_DIR / f"{sha256}.meta.json"

    if canonical.exists():
        binary.unlink()  # duplicate; drop subdir copy
    else:
        shutil.move(str(binary), str(canonical))

    sidecar.write_text(
        json.dumps({
            "sha256":        sha256,
            "size":          size,
            "filetype":      _filetype(header),
            "honeypot":      honeypot,
            "original_name": original,
            "captured_at":   captured_at,
            "processed_at":  _now(),
            "src_ip":        capture.get("src_ip"),
            "url":           capture.get("url"),
            "session_id":    capture.get("session_id"),
            "protocol":      capture.get("protocol"),
        }),
        encoding="utf-8",
    )

    cap = _capture_path(binary)
    if cap.exists():
        cap.unlink()

    src = capture.get("src_ip") or "?"
    print(
        f"[{_now()}] canonicalised {sha256[:12]}  from={honeypot}/{original}  src={src}",
        flush=True,
    )


def _scan_once() -> None:
    if not INBOX_DIR.is_dir():
        return
    for subdir in INBOX_DIR.iterdir():
        if not subdir.is_dir():
            continue
        for path in subdir.iterdir():
            if not path.is_file() or path.name.endswith(".capture.json"):
                continue
            try:
                _process(path, subdir.name)
            except OSError as exc:
                print(f"[{_now()}] error  {subdir.name}/{path.name}: {exc}", flush=True)


def main() -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"[{_now()}] metadata addon started  inbox={INBOX_DIR}  "
        f"poll={POLL_SECS}s  settle={MTIME_SETTLE_SECS}s",
        flush=True,
    )
    while True:
        _scan_once()
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
