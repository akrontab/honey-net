"""
Metadata extractor — tails honeypot event logs and writes {sha256}.meta.json
sidecars to the shared inbox so the analyzer can submit samples to the catalog.

Configured via env vars:
  SOURCES     JSON array of {format, log, honeypot}. Supported formats: cowrie_jsonl
  INBOX_DIR   Where to write .meta.json files (default /inbox)
  STATE_DIR   Where to persist log offsets across restarts (default /state)
  POLL_SECS   How often to check for new log lines (default 2)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

INBOX_DIR = Path(os.getenv("INBOX_DIR", "/inbox"))
STATE_DIR = Path(os.getenv("STATE_DIR", "/state"))
POLL_SECS = int(os.getenv("POLL_SECS", "2"))
SOURCES   = json.loads(os.getenv("SOURCES", "[]"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filename_from_url(url: str, fallback: str) -> str:
    if url:
        part = url.rstrip("/").rsplit("/", 1)[-1]
        if part and "." in part:
            return part
    return fallback


def _write_sidecar(sha256: str, src_ip: str, url: str, filename: str, honeypot: str, timestamp: str) -> None:
    path = INBOX_DIR / f"{sha256}.meta.json"
    if path.exists():
        return
    path.write_text(json.dumps({
        "sha256":    sha256,
        "src_ip":    src_ip,
        "url":       url,
        "filename":  filename,
        "honeypot":  honeypot,
        "timestamp": timestamp,
    }), encoding="utf-8")
    print(f"[{_now()}] sidecar  {sha256[:12]}  src={src_ip}  url={url}", flush=True)


# ── Format parsers ────────────────────────────────────────────────────────────

def _parse_cowrie_jsonl(line: str, honeypot: str) -> None:
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return
    if ev.get("eventid") != "cowrie.session.file_download":
        return
    sha256 = ev.get("shasum", "")
    if not sha256:
        return
    url      = ev.get("url", "")
    src_ip   = ev.get("src_ip", "unknown")
    ts       = ev.get("timestamp", _now())
    filename = _filename_from_url(url, sha256)
    _write_sidecar(sha256, src_ip, url, filename, honeypot, ts)


PARSERS: dict = {
    "cowrie_jsonl": _parse_cowrie_jsonl,
}


# ── Log tailer ────────────────────────────────────────────────────────────────

class LogTailer:
    def __init__(self, log_path: Path, honeypot: str, fmt: str, state_path: Path):
        self.log_path   = log_path
        self.honeypot   = honeypot
        self.parse      = PARSERS[fmt]
        self.state_path = state_path
        self.offset     = self._load_offset()

    def _load_offset(self) -> int:
        try:
            return int(self.state_path.read_text().strip())
        except (FileNotFoundError, ValueError):
            return 0

    def _save_offset(self) -> None:
        self.state_path.write_text(str(self.offset))

    def poll(self) -> None:
        if not self.log_path.exists():
            return
        with self.log_path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(self.offset)
            for line in f:
                stripped = line.strip()
                if stripped:
                    self.parse(stripped, self.honeypot)
            self.offset = f.tell()
        self._save_offset()


def main() -> None:
    if not SOURCES:
        sys.exit("SOURCES env var is empty — nothing to watch")

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    tailers = []
    for i, src in enumerate(SOURCES):
        fmt      = src.get("format", "")
        log_file = src.get("log", "")
        honeypot = src.get("honeypot", f"unknown-{i}")

        if fmt not in PARSERS:
            sys.exit(f"Unknown format '{fmt}' for source {i} — supported: {list(PARSERS)}")
        if not log_file:
            sys.exit(f"Missing 'log' field in source {i}")

        tailers.append(LogTailer(
            log_path   = Path(log_file),
            honeypot   = honeypot,
            fmt        = fmt,
            state_path = STATE_DIR / f"offset-{i}.txt",
        ))
        print(f"[{_now()}] watching  {log_file}  format={fmt}  honeypot={honeypot}", flush=True)

    print(f"[{_now()}] metadata extractor started  inbox={INBOX_DIR}", flush=True)

    while True:
        for t in tailers:
            t.poll()
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
