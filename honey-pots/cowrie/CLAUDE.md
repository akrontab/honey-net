# Cowrie Honeypot Package

SSH (port 22) and Telnet (port 23) honeypot. Captures full PTY sessions, commands, malware download attempts, attacker-planted SSH keys, and brute-force credentials.

Real SSH is on port 65022 (Tailscale only) — managed by `server-config/`.

## Logs and samples

```
/opt/<server>/cowrie/volumes/logs/cowrie.json             # attacker session events (JSONL)
/opt/<server>/cowrie/volumes/var/log/cowrie/cowrie.log    # twistd application log
/opt/<server>/inbox/cowrie/                               # captured binaries + .capture.json sidecars
```

Cowrie writes downloaded binaries to `/samples` (bind-mounted from the inbox). The **capture-writer sidecar** tails `cowrie.json` and, on every `cowrie.session.file_download`, writes `<outfile>.capture.json` next to the binary containing `{src_ip, url, session_id, captured_at}`. The `metadata` addon canonicalises binary + sidecar into `/opt/<server>/inbox/<sha256>` + `<sha256>.meta.json`.

Shipped to Loki as `{job="cowrie"}` (raw) and `{job="events", honeypot="cowrie"}` (normalised).

## Normalised event mapping

| Cowrie `eventid` | `event_type` |
|---|---|
| `cowrie.session.connect` | `connect` |
| `cowrie.login.success` / `cowrie.login.failed` | `login` |
| `cowrie.command.input` / `cowrie.command.failed` | `command` |
| `cowrie.session.file_download` | `download` |
| `cowrie.session.closed` | `session_end` |
| (other) | dropped |

`payload` carries the command `input` only. On `download` events `payload` is `null` and the URL lives in `meta.url`. `protocol` is only populated on `cowrie.session.connect`; downstream events carry `null` and must be joined on `session_id` to recover protocol (see normalized-schema-plan.md Q5 — deferred).

### Standard `meta` keys emitted

Vocabulary defined in `honey-pots/CLAUDE.md`. Cowrie's `remap` derives:

| `event_type` | `meta` key | Derived from |
|---|---|---|
| `login` | `login_success` | `eventid == "cowrie.login.success"` (true/false) |
| `command` | `command_success` | `eventid == "cowrie.command.input"` (vs `.failed`) |
| `download` | `url` | `raw.url` |
| `download` | `dl_host` | host of `raw.url` (`parse_url`) |
| `download` | `dl_filename` | last path segment of `raw.url` |

**Deferred (Q5):** `client_fingerprint` (HASSH) and `client_version` arrive on separate eventids (`cowrie.client.kex`, `cowrie.client.version`) the remap currently drops, so they need session correlation before they can be attached to the `connect` event. Not yet emitted.

## Gotchas

### Mount the full etc/ directory, not individual files
Cowrie declares a Docker VOLUME for `/cowrie/cowrie-git/etc`. Individual file bind-mounts get shadowed by it. Mount the whole directory.

### Container uid is 999
Volume directories must be `chown -R 999:999` (`fragment.sh` handles this). The shared inbox subdir `/opt/<server>/inbox/cowrie/` is `chmod 777` so capture-writer (root) and cowrie (999) can both write.

### `state_path` is required in cowrie.cfg
Without `state_path = var/lib/cowrie` under `[honeypot]`, auth raises `NoOptionError` and every login silently fails.

### Use `auth_class = UserDB`, not `AuthRandom`
`AuthRandom` ignores `userdb.txt`. Use `UserDB` with `root:x:*` to accept any password for root.

### Two-stage attack pattern
Attackers often plant an SSH key then reconnect with that key for the payload. Adding planted keys to `cowrie/etc/authorized_keys` captures the stage-2 session.

### JSON log is redirected, twistd log is not
`output_jsonlog.logfile = /cowrie-logs/cowrie.json` writes to the conventional `./volumes/logs/cowrie.json` so `get_logs.py` finds it without per-package config. The twistd application log stays at its default `./volumes/var/log/cowrie/cowrie.log` — nothing downstream consumes it.
