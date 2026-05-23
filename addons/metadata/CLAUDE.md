# metadata addon

Watches the shared inbox for new malware samples and writes `{sha256}.meta.json`
sidecars. The malware-sender addon reads these sidecars to submit samples to the
malware catalog.

## Responsibility

Single responsibility: for each binary that lands in the inbox, verify its SHA-256
hash (the filename), detect its file type from magic bytes, and write a sidecar.
No log parsing, no knowledge of any honeypot's log format.

## How it works

1. Poll `INBOX_DIR` every `POLL_SECS` seconds
2. For each file whose name is a 64-character hex string (SHA-256) with no matching sidecar:
   - Read the file in one pass: capture the first 4 bytes for magic-byte detection and compute SHA-256
   - If the computed hash doesn't match the filename the file is still being written — skip and retry next poll
   - Write `{sha256}.meta.json`

## Sidecar schema

```json
{
  "sha256":    "abc123...",
  "size":      12345,
  "filetype":  "elf",
  "timestamp": "2026-05-19T12:00:00+00:00"
}
```

## Detected file types

| Magic bytes | `filetype` |
|-------------|------------|
| `\x7fELF`   | `elf`      |
| `MZ`        | `pe`       |
| Mach-O fat/32/64 | `macho` |
| (anything else) | `data` |

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `INBOX_DIR` | `/inbox` | Where to watch for samples and write `.meta.json` files |
| `POLL_SECS` | `2` | Polling interval in seconds |

## Volume mounts (in docker-compose.yml)

| Container path | Host path | Purpose |
|----------------|-----------|---------|
| `/inbox` | `../inbox` | Watch for binaries; write `.meta.json` sidecars |

The inbox is the only mount — no log directories are needed.
