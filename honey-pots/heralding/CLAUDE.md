# Heralding Honeypot Package

Multi-protocol credential honeypot. Exposes twelve services (FTP, Telnet, SSH,
SMTP, HTTP, HTTPS, POP3, IMAP, MySQL, PostgreSQL, VNC, SOCKS5) and logs every
credential attempt as a CSV row in real time, plus a JSONL session summary on
disconnect. Pure credential capture — no session emulation, no binary download.

**Wrap mode:** Mode B — thin Dockerfile pinning `heralding==1.0.7` from PyPI.
We do not control heralding's source; we own the Dockerfile and config only.
See `docs/wrapping-upstream-honeypots-plan.md` for the general pattern.

**Status:** Reference / template package. Not in `honey-net.json`. To promote
into the net see "Promoting to production" below.

## Ports

| Port | Protocol |
|------|----------|
| 21   | FTP |
| 22   | SSH |
| 23   | Telnet |
| 25   | SMTP |
| 80   | HTTP |
| 110  | POP3 |
| 143  | IMAP |
| 443  | HTTPS |
| 1080 | SOCKS5 |
| 3306 | MySQL |
| 5432 | PostgreSQL |
| 5900 | VNC |

RDP (3389), POP3S (995), IMAPS (993), SMTPS (465) are present in `heralding.yml`
but disabled — enable and open the corresponding UFW rules in `fragment.sh` if
you want them.

## Logs

```
/opt/<server>/heralding/volumes/logs/log_auth.csv      # one row per credential attempt (real-time)
/opt/<server>/heralding/volumes/logs/log_session.json  # JSONL, one object per session (on close)
/opt/<server>/heralding/volumes/logs/log_session.csv   # session summary CSV (on close)
```

`log_auth.csv` is the primary source for the normalized event stream — written
immediately on each auth attempt, so latency to Loki is minimal.

`log_session.json` is the raw `{job="heralding"}` stream — richer per-session
detail (protocol-specific auxiliary data), but arrives only when the session ends.

Shipped to Loki as `{job="heralding"}` (raw, from `log_session.json`) and
`{job="events", honeypot="heralding"}` (normalised, from `log_auth.csv`).

## log_auth.csv columns

```
timestamp, auth_id, session_id, source_ip, source_port, destination_port, protocol, username, password
```

`protocol` is uppercase in the file (e.g. `FTP`, `SSH`); the Vector remap
lowercases it before shipping.

## Normalised event mapping

Heralding emits only one meaningful event type for the normalized stream: login.
It never grants access, so all events are credential-collection attempts.

| Source file | `event_type` |
|---|---|
| `log_auth.csv` row | `login` |

`connect` and `session_end` are available in `log_session.json` / `log_session.csv`
(session open/close times, duration, auth_attempts count) but are not currently
mapped to the normalized stream — heralding's value is in the per-attempt credential
rows, not session-level summaries.

### Standard `meta` keys emitted

| `event_type` | `meta` key | Value |
|---|---|---|
| `login` | `login_success` | always `"false"` — heralding never authenticates |
| `login` | `auth_method` | always `"password"` — heralding is a password-capture pot |

`client_fingerprint` / `fingerprint_type` / `client_version` are not emitted;
heralding does not extract SSH HASSH or TLS JA3 (it operates at the
credential layer, not the transport-fingerprint layer).

## Gotchas

### Wrap mode: we own the config, not the code
`heralding.yml` is our file — adjust ports, banners, and which protocols are
enabled here. The upstream code in `heralding==1.0.7` is not modified. If you
bump the pin, diff the new default `heralding.yml` from the upstream repo against
ours and reconcile any new/removed keys.

### Log paths are absolute in heralding.yml
The default config uses relative log paths (relative to CWD). We set them as
absolute `/logs/...` so heralding can run from `WORKDIR=/data` (where it writes
ephemeral TLS cert files) while writing logs to the `/logs` volume. Never change
these back to relative paths.

### TLS cert files land in WORKDIR=/data
For HTTPS and any other TLS capability heralding auto-generates a self-signed cert
in its working directory (`/data` inside the container). This directory is NOT a
mounted volume, so certs are ephemeral — regenerated on each container restart.
Clients do not validate the cert anyway, so this is fine.

### network_mode: host for src_ip preservation
Like Cowrie, heralding uses `network_mode: host` + the rootlesskit pasta port
driver to preserve the real attacker IP in `log_auth.csv`. Without this, Docker's
userland proxy rewrites the source IP to the bridge gateway address.
`ports:` and `networks:` are absent from the compose service (incompatible with
host mode); Vector communicates with heralding only via the shared log volume.

### Dedicate a server — port collision risk
Heralding claims 12 ports including :22, :80, :443, :3306. Co-deploying with
Cowrie (needs :22/:23) or the HTTP/MySQL honeypots (need :80/:443/:3306) is a
port conflict. Heralding is best on its own dedicated Nanode.

### hash_cracker is disabled
The upstream default enables heralding's hash_cracker (requires `wordlist.txt`
in WORKDIR). We disable it — it's irrelevant to honey-net's collection goals
and would require mounting a wordlist into the container.

### csv rows vs JSON: one is real-time, one is deferred
`log_auth.csv` rows land immediately on each auth attempt — Vector picks them
up with minimal latency. `log_session.json` objects only appear when the session
closes (attacker disconnects or timeout). Do not use `log_session.json` as the
primary source for alerting on new credentials.

## Promoting to production

1. Add `honey-net.json` entry: `"honeypots": ["heralding"]`, `"ports": [21,22,23,25,80,110,143,443,1080,3306,5432,5900]`
2. Generate SSH key at the path specified in `ssh_key`
3. Hash-lock the pin: build with `--require-hashes` from a locked `requirements.txt`
   and pin the base image by digest (see `docs/wrapping-upstream-honeypots-plan.md`)
4. Add a Grafana dashboard under `log-stack/deploy/grafana/provisioning/dashboards/`
5. `python scripts/provision.py --server <name>`
