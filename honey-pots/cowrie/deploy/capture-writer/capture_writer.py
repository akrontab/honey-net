"""
Cowrie capture-sidecar writer.

Tails cowrie.json. On every cowrie.session.file_download event, writes
<outfile-basename>.capture.json next to the binary in /samples with the source
IP, URL, and session id. The metadata addon merges these fields into the
canonical {sha256}.meta.json sidecar during canonicalisation.

Configured via env vars:
  COWRIE_LOG   Path to cowrie.json inside the container (default /cowrie-logs/cowrie.json)
  SAMPLES_DIR  Where cowrie drops binaries (default /samples)
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

COWRIE_LOG  = Path(os.getenv("COWRIE_LOG",  "/cowrie-logs/cowrie.json"))
SAMPLES_DIR = Path(os.getenv("SAMPLES_DIR", "/samples"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(path: Path):
    while not path.exists():
        time.sleep(2)
    with path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)  # seek to end — only react to new events
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            yield line


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"[{_now()}] capture-writer started  log={COWRIE_LOG}  samples={SAMPLES_DIR}",
        flush=True,
    )

    for line in _tail(COWRIE_LOG):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("eventid") != "cowrie.session.file_download":
            continue

        outfile  = event.get("outfile") or ""
        basename = Path(outfile).name
        if not basename:
            continue

        sidecar = SAMPLES_DIR / f"{basename}.capture.json"
        try:
            sidecar.write_text(
                json.dumps({
                    "src_ip":      event.get("src_ip"),
                    "url":         event.get("url"),
                    "session_id":  event.get("session"),
                    "captured_at": event.get("timestamp"),
                }),
                encoding="utf-8",
            )
            print(
                f"[{_now()}] capture  {basename[:16]}  src={event.get('src_ip')}",
                flush=True,
            )
        except OSError as exc:
            print(f"[{_now()}] error writing {sidecar}: {exc}", flush=True)


if __name__ == "__main__":
    main()
