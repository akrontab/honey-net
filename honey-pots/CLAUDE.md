# Adding a Honeypot Package

A honeypot package is a self-contained folder under `honey-pots/` that teaches `provision.py` and `redeploy.py` how to deploy a service. Adding one requires no changes to Terraform or `server-config/`.

To create a new package, copy an existing one (`cowrie/` is simplest, `mysql/` for a built-locally Python service) and adapt. The rest of this file documents the contracts those examples follow.

## Filesystem conventions

| Concern | Convention |
|---|---|
| JSON log on host | `./volumes/logs/<honeypot>.json` (filename = package name) |
| JSON log in vector container | `/logs/<honeypot>/<honeypot>.json` (assembler re-roots) |
| Sample drop on host | `/opt/<server>/inbox/<honeypot>/` |
| Sample drop in honeypot container | `/samples/` (per-honeypot mount) |
| Shared inbox parent | `/opt/<server>/inbox/` — created by `server-config/setup.sh` `chmod 777` |
| Per-honeypot inbox subdir | created by the honeypot's `fragment.sh` |

Honeypots write samples with whatever filename their upstream code picks (sha256 for cowrie, md5 for dionaea). The `metadata` addon canonicalises to `/inbox/<sha256>` + `/inbox/<sha256>.meta.json`. Honeypots that don't capture samples skip the `/samples` mount and the `mkdir inbox/<name>` step.

## docker-compose.yml conventions

Each honeypot's compose file is included into a generated top-level compose by `provision.py` — it must not declare networks or volumes that conflict with siblings.

- All services on a `honeypot` network (driver: bridge), declared in each compose for idempotency.
- Always `restart: unless-stopped` and `security_opt: [no-new-privileges:true]`.
- Set `deploy.resources.limits` — Nanode has 1GB RAM total.
- Include a `vector` service that ships `./volumes/logs/` + host `/var/log` to Loki.

## vector/vector.toml — normalized event schema

Each honeypot's Vector includes a `remap` transform that emits a parallel `{job="events", honeypot=<name>}` stream alongside the raw `{job="<honeypot>"}` stream. The unified schema:

```json
{
  "timestamp":     "ISO-8601 UTC",
  "honeypot":      "<package name>",
  "protocol":      "ssh|telnet|mysql|smb|ftp|...",
  "src_ip":        "1.2.3.4",
  "src_port":      54321,
  "session_id":    "...",
  "event_type":    "connect|login|command|query|download|session_end",
  "username":      "root",
  "password":      "...",
  "payload":       "...",
  "sample_sha256": "..."
}
```

All fields except `timestamp`, `honeypot`, `src_ip`, and `event_type` may be `null`. Events whose source `eventid`/`type` doesn't map to a known `event_type` are dropped via `abort`.

The Loki job label (`labels.job`) is what LogQL queries filter on — use a short lowercase name matching the package name. Every honeypot also ships `auth.log` and `syslog` from `/hostlogs` to `{job="auth"}` / `{job="syslog"}`.

## setup/fragment.sh

`provision.py` concatenates `server-config/setup.sh` with each honeypot's `fragment.sh` in the order listed under `"honeypots"` in `honey-net.json`. The result is the `setup.sh` that lands on the server.

Environment variables available:

| Variable | Value |
|---|---|
| `$DEPLOY_DIR` | `/opt/<server-name>` — where files are rsynced |
| `$SERVER_NAME` | Server name from honey-net.json |
| `$TAILSCALE_IP` | Server's Tailscale IP (set after Tailscale joins) |
| `$REAL_SSH_PORT` | `65022` |
| `$LOKI_HOST` | log-stack Tailscale IP (read from state.json by setup.sh) |

Fragment responsibilities:
- **Open UFW ports** for the public-facing service.
- **Create volume directories** (Docker assigns wrong ownership if you let it create them lazily).
- **Create the per-honeypot inbox subdir** with `chmod 777` if it captures samples.
- **Fix ownership** for non-root container UIDs (Cowrie is 999).
- **Build locally-built images explicitly in sequence.** Never `docker compose up --build` — concurrent BuildKit crashes dockerd (see `mysql/CLAUDE.md`).
- **Run `docker compose up -d` only if this fragment is designed to always be last.** Cowrie's fragment does not — it is always followed by addons on real servers. MySQL and dionaea fragments always run `up -d` (designed as standalone-terminal honeypots). Malware-sender always runs `up -d` as the terminal addon. On multi-component servers, a non-terminal fragment that runs `up -d` will start the stack before later images are built, then the final fragment starts it again.

## honey-net.json entry

```json
{
  "name": "my-server",
  "type": "honeypot",
  "ssh_key": "~/.ssh/my-server-linode",
  "honeypots": ["cowrie", "my-honeypot"],
  "ports": [22, 23, 9999],
  "tailscale_ephemeral": true
}
```

`tailscale_ephemeral: true` auto-removes the Tailscale node when the VM is destroyed — use for all honeypot servers.

## Checklist for a new honeypot

- [ ] `deploy/docker-compose.yml` (+ `../inbox/<name>:/samples` mount if it captures binaries)
- [ ] `deploy/vector/vector.toml` (sources + normalising transform + sinks)
- [ ] `deploy/.env.example`
- [ ] `deploy/setup/fragment.sh`
- [ ] `CLAUDE.md` (protocol, log paths, event mapping, gotchas)
- [ ] `test.py` (smoke test — see existing honeypots for the `_lib` import pattern)
- [ ] Entry in `honey-net.json`
- [ ] SSH key pair at the `ssh_key` path
- [ ] `python scripts/provision.py --server <name>`
- [ ] Grafana dashboard under `log-stack/deploy/grafana/provisioning/dashboards/`
