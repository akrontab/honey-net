# metadata addon

Tails honeypot event logs and writes `{sha256}.meta.json` sidecars to the shared
inbox. The analyzer addon reads these sidecars to submit samples to the malware catalog.

## Responsibility

Single responsibility: translate honeypot-specific event log entries into a standard
metadata file that any downstream consumer can read without knowing the log format.

The honeypot (e.g. Cowrie) only needs to drop binaries into `/inbox`. This addon
handles all metadata extraction.

## Sidecar schema

```json
{
  "sha256":    "abc123...",
  "src_ip":    "1.2.3.4",
  "url":       "http://attacker.com/malware.sh",
  "filename":  "malware.sh",
  "honeypot":  "cowrie",
  "timestamp": "2026-05-19T12:00:00+00:00"
}
```

## Log offset tracking

The service records its byte offset in each log file under `/state/offset-{n}.txt`.
On restart it resumes from where it left off, so no events are missed or double-processed.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `METADATA_SOURCES` | (required) | JSON array of `{format, log, honeypot}` objects (shell placeholder; passed to container as `SOURCES`) |
| `INBOX_DIR` | `/inbox` | Where to write `.meta.json` files |
| `STATE_DIR` | `/state` | Where to persist log offsets |
| `POLL_SECS` | `2` | Polling interval in seconds |

## Supported formats

| Format key | Honeypot | Event watched |
|------------|----------|---------------|
| `cowrie_jsonl` | Cowrie | `cowrie.session.file_download` |

## Volume mounts (in docker-compose.yml)

| Container path | Host path | Purpose |
|----------------|-----------|---------|
| `/inbox` | `../inbox` | Write `.meta.json` sidecars |
| `/state` | `./volumes/state` | Persist log offsets |

Log mounts (e.g. `/logs/cowrie`, `/logs/mysql`) are **not** hardcoded here. They are
injected at assemble time by `assemble_honeypot_package` in `_lib.py`, which reads
each honeypot's `deploy/logs.json` and adds the corresponding `:ro` mounts. See
`honey-pots/CLAUDE.md` § 5 for the `logs.json` convention.

## Adding a new format

Add a parser function to `metadata.py` and register it in `PARSERS`:

```python
def _parse_my_format(line: str, honeypot: str) -> None:
    ev = json.loads(line)
    if ev.get("type") != "download":
        return
    _write_sidecar(ev["hash"], ev["ip"], ev["url"], ev["name"], honeypot, ev["ts"])

PARSERS["my_format"] = _parse_my_format
```

Then ensure the honeypot's `deploy/logs.json` declares the log directory so the
assembler mounts it (see `honey-pots/CLAUDE.md` § 5). Finally, configure the source
in the server's `.env`:
```
METADATA_SOURCES=[{"format":"my_format","log":"/logs/myhoneypot/events.json","honeypot":"myhoneypot"}]
```
