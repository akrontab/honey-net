# metadata addon

Canonicalises malware samples dropped by honeypots into per-honeypot subdirs of the
shared inbox. For each binary it computes the sha256, moves the file to
`/inbox/<sha256>`, and writes a `/inbox/<sha256>.meta.json` sidecar that merges
filesystem-derived fields with any honeypot-supplied provenance.

The malware-sender addon reads the canonical sidecars and submits to the catalog.

## Responsibility

Single responsibility: turn whatever a honeypot dropped into a deterministically-named
canonical sample with a complete sidecar. No log parsing, no knowledge of any specific
honeypot's log format — honeypot identity comes from the subdir the file was found in,
and per-event provenance comes from optional `<name>.capture.json` sidecars dropped
alongside the binary by the honeypot.

## How it works

1. Poll `INBOX_DIR/*/` (per-honeypot subdirs) every `POLL_SECS` seconds
2. For each binary file (skipping `*.capture.json` sidecars):
   - Skip if `mtime` is more recent than `MTIME_SETTLE_SECS` (file still being written)
   - Read any co-located `<name>.capture.json` for `{src_ip, url, session_id, captured_at}`
   - Compute sha256 + detect file type from magic bytes
   - Move binary to `INBOX_DIR/<sha256>` (or delete duplicate if canonical already exists)
   - Write `INBOX_DIR/<sha256>.meta.json` merging derived + captured fields
   - Delete the `<name>.capture.json` sidecar

## Sidecar schema

```json
{
  "sha256":        "abc123...",
  "size":          12345,
  "filetype":      "elf",
  "honeypot":      "cowrie",
  "original_name": "bin.elf",
  "captured_at":   "2026-05-27T11:59:50+00:00",
  "processed_at":  "2026-05-27T12:00:00+00:00",
  "src_ip":        "1.2.3.4",
  "url":           "http://attacker.example/x.elf",
  "session_id":    "a1b2c3d4"
}
```

Fields:

| Field | Source |
|---|---|
| `sha256` | computed from the binary |
| `size` | computed from the binary |
| `filetype` | magic-byte detection (`elf`, `pe`, `macho`, `data`) |
| `honeypot` | parent subdir name (e.g. `cowrie`, `dionaea`) |
| `original_name` | filename in the subdir before canonical rename |
| `captured_at` | from the capture sidecar if present, otherwise the binary's mtime |
| `processed_at` | when metadata wrote the sidecar |
| `src_ip` / `url` / `session_id` | from the capture sidecar; `null` if absent |

Honeypots that emit a capture sidecar get full provenance. Honeypots whose upstream code
we can't easily patch (e.g. dionaea) get whatever can be derived from the path —
`src_ip`/`url`/`session_id` will be `null` and analysts must pivot through the raw log
stream to recover provenance.

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
| `INBOX_DIR` | `/inbox` | Root inbox dir (walks every `<honeypot>/` subdir within it) |
| `POLL_SECS` | `2` | Polling interval in seconds |
| `MTIME_SETTLE_SECS` | `5` | Seconds the file must have been idle before processing |

## Volume mounts (in docker-compose.yml)

| Container path | Host path | Purpose |
|----------------|-----------|---------|
| `/inbox` | `../inbox` | Walk subdirs, write canonical files + sidecars |

## Gotchas

### File-still-being-written detection
Earlier versions named files by sha256 at drop time, so a mismatched hash meant "still
being written." Honeypots now drop files with arbitrary names, so we use mtime stability
instead (`MTIME_SETTLE_SECS`, default 5s). Tune up if you see partially-hashed files
showing up canonicalised; tune down for snappier processing.

### Capture sidecar race window
If a honeypot's capture-writer is slower than `MTIME_SETTLE_SECS`, the canonical sidecar
for that sample will lack `src_ip`/`url`/`session_id`. The raw log still has the data —
analysts can pivot via `sha256`. In practice cowrie's capture-writer is sub-second so
this is rarely observed.
