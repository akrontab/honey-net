# metadata addon

Tails honeypot event logs and writes `{sha256}.meta.json` sidecars to the shared
inbox. The malware-sender addon reads these sidecars to submit samples to the malware catalog.

## Responsibility

Single responsibility: translate honeypot-specific event log entries into a standard
metadata file that any downstream consumer can read without knowing the log format.

## Sidecar schema

```json
{
  "sha256":    "abc123...",
  "src_ip":    "1.2.3.4",
  "url":       "http://attacker.com/malware.sh",
  "filename":  "malware.sh",
  "timestamp": "2026-05-19T12:00:00+00:00"
}
```

## Log offset tracking

The service records its byte offset in each log file under `/state/offset-{n}.txt`.
On restart it resumes from where it left off, so no events are missed or double-processed.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `SOURCES` | (injected by assembler) | JSON array of `{format, log}` — auto-generated from each honeypot's `logs.json` |
| `INBOX_DIR` | `/inbox` | Where to write `.meta.json` files |
| `STATE_DIR` | `/state` | Where to persist log offsets |
| `POLL_SECS` | `2` | Polling interval in seconds |

`SOURCES` is never set manually. The assembler reads each honeypot's `logs.json` for entries
with a `format` field and injects the resulting JSON array into the assembled docker-compose.

## Supported formats

| Format key | Event watched |
|------------|---------------|
| `cowrie_jsonl` | `cowrie.session.file_download` |

## Volume mounts (in docker-compose.yml)

| Container path | Host path | Purpose |
|----------------|-----------|---------|
| `/inbox` | `../inbox` | Write `.meta.json` sidecars |
| `/state` | `./volumes/state` | Persist log offsets |

Log mounts (e.g. `/logs/cowrie`) are injected at assemble time from each honeypot's
`logs.json`. See `honey-pots/CLAUDE.md` § 5 for the convention.

## Adding a new format

Add a parser to `metadata.py` and register it in `PARSERS`:

```python
def _parse_my_format(line: str) -> None:
    ev = json.loads(line)
    if ev.get("type") != "download":
        return
    _write_sidecar(ev["hash"], ev["ip"], ev["url"], ev["name"], ev["ts"])

PARSERS["my_format"] = _parse_my_format
```

Then add `"format": "my_format"` to the relevant entry in the honeypot's `logs.json`.
The assembler picks it up automatically — no `.env` changes needed.
