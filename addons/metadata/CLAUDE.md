# metadata addon

Canonicalises malware samples dropped by honeypots into per-honeypot subdirs of the shared inbox. For each binary it computes sha256, moves the file to `/inbox/<sha256>`, and writes a `/inbox/<sha256>.meta.json` sidecar merging filesystem-derived fields with any honeypot-supplied provenance.

The malware-sender addon reads the canonical sidecars and submits to the catalog.

## Responsibility

Single responsibility: turn whatever a honeypot dropped into a deterministically-named canonical sample with a complete sidecar. No log parsing, no knowledge of any specific honeypot's log format — honeypot identity comes from the parent subdir, and per-event provenance comes from optional `<name>.capture.json` sidecars the honeypot drops alongside the binary.

## How it works

Poll `INBOX_DIR/*/` (per-honeypot subdirs) every `POLL_SECS`. For each binary file (skipping `*.capture.json`):
1. Skip if `mtime` is more recent than `MTIME_SETTLE_SECS` (file still being written)
2. Read any co-located `<name>.capture.json` for `{src_ip, url, session_id, captured_at}`
3. Compute sha256 + detect file type from magic bytes
4. Move binary to `INBOX_DIR/<sha256>` (or delete duplicate if canonical exists)
5. Write `INBOX_DIR/<sha256>.meta.json` merging derived + captured fields
6. Delete the `<name>.capture.json` sidecar

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

| Field | Source |
|---|---|
| `sha256` / `size` | computed from binary |
| `filetype` | magic-byte detection (`elf`, `pe`, `macho`, `data`) |
| `honeypot` | parent subdir name |
| `original_name` | filename before canonical rename |
| `captured_at` | capture sidecar if present, else binary mtime |
| `processed_at` | when metadata wrote the sidecar |
| `src_ip` / `url` / `session_id` | capture sidecar; `null` if absent (e.g. dionaea) |

## Config

| Env var | Default | Description |
|---|---|---|
| `INBOX_DIR` | `/inbox` | Root inbox dir |
| `POLL_SECS` | `2` | Polling interval |
| `MTIME_SETTLE_SECS` | `5` | Idle seconds before processing |

## Gotchas

### File-still-being-written detection uses mtime
Earlier versions trusted sha256-named filenames at drop time, so a mismatched hash meant "still being written." Honeypots now drop arbitrary names, so we use mtime stability. Tune `MTIME_SETTLE_SECS` up if you see partial-hash files canonicalised, down for snappier processing.

### Capture-sidecar race window
If a honeypot's capture-writer is slower than `MTIME_SETTLE_SECS`, the canonical sidecar lacks `src_ip` / `url` / `session_id`. The raw log still has them — pivot via `sha256`. Cowrie's capture-writer is sub-second so this is rarely observed.
