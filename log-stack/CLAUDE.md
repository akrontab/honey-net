# log-stack

Grafana + Loki host for the honey-net. Receives logs from honeypots and malware-catalog over Tailscale. Never exposed to the public internet.

## Tailscale-only binding (not firewall)

Docker modifies iptables directly and bypasses UFW. Grafana (3000) and Loki (3100) instead bind to `${TAILSCALE_IP}` (not `0.0.0.0`), so the kernel only routes them via the Tailscale interface. **If `TAILSCALE_IP` is wrong or unset, the ports fall back to all-interfaces and become publicly reachable.** Always verify `.env` after recreating the server.

## LogQL streams

```
{job="cowrie"} / {job="mysql"}                      # raw service events
{job="auth"} / {job="syslog"}                       # host logs from honeypot
{job="catalog"}                                      # malware-catalog audit events
{job="events"}                                       # normalized cross-honeypot stream
{job="events", honeypot="cowrie"}                    # one honeypot, normalized
{job="events"} | json | event_type = "login"         # logins across all honeypots
```

The `{job="events"}` stream is produced by per-honeypot VRL transforms — see `honey-pots/CLAUDE.md` for the unified schema and `honey-pots/<name>/CLAUDE.md` for field mappings.

## Dashboard contract

Dashboards live under `deploy/grafana/provisioning/dashboards/` in a **four-folder taxonomy**:

| Folder | Purpose | Stream |
|---|---|---|
| `Triage/` | Situational awareness — what's happening now | `{job="events"}` only |
| `Hunt/` | Attacker investigation — campaigns, credentials, downloads, sessions | `{job="events"}` only |
| `Operate/` | Fleet and pipeline health | `{job="events"}` + host logs |
| `Deep-dives/` | Per-protocol forensics | raw `{job="<honeypot>"}` |

**The hard rule:** Triage / Hunt / Operate boards query `{job="events"}` only — never raw `eventid`. Deep-dives are where raw stream detail belongs.

**`foldersFromFilesStructure: true`** is set in `dashboards.yml` so subdirectory names become Grafana folders automatically.

**Navigation links** in the `links` array of each workflow-tier board connect: Triage → Hunt/Operate, Hunt boards → each other, Hunt/attacker-profile → all Deep-dives.

**Panel data links** carry clicked values into other dashboards: "Source IP" cells link to `hunt-attacker-profile?var-src_ip=…`; "Download Host" cells link to `hunt-campaign-pivot?var-dl_host=…`.

A new honeypot that fills the `{job="events"}` contract appears in every Triage/Hunt/Operate board with zero dashboard edits. Add a Deep-dive only for per-protocol raw detail.

## Gotchas

### `.env` is not deployed by provision.py — intentional
`provision.py` excludes `.env`. `setup.sh` generates it at provision time with `TAILSCALE_IP` auto-detected from `tailscale ip -4`. If the Tailscale IP changes (reissued key, different node), edit `/opt/log-stack/.env` and `docker compose down && up -d` — the IP is baked into running containers at startup.

### fail2ban will ban your own IP during setup
Setup enables fail2ban on port 65022. Failed SSH attempts during debugging get you banned. Symptom: port 65022 times out from outside but `ssh -p 65022 root@127.0.0.1` from the Linode LISH console works. Unban: `fail2ban-client set sshd unbanip <your-ip>`.

### sshd port change requires disabling socket activation (Ubuntu 24.04)
Ubuntu 24.04 runs sshd via `ssh.socket`. The socket holds the port binding and ignores `sshd_config`'s `Port` directive — `systemctl restart ssh` alone does not move the port. `setup.sh` disables `ssh.socket` before restarting. If you hit this on an already-provisioned box:
```bash
systemctl stop ssh.socket && systemctl disable ssh.socket
systemctl daemon-reload && systemctl restart ssh
ss -tlnp | grep sshd    # should show 65022
```

### Grafana provisioning permission denied on first start
`cp -r` in `setup.sh` creates root-owned files. Grafana (uid 472) silently skips all provisioning when it can't read `/etc/grafana/provisioning/` — no dashboards or datasources appear but Grafana starts cleanly. `setup.sh` now runs `chmod -R a+rX "${DEPLOY_DIR}"` after `cp`. `redeploy.py` also chmods after every rsync. To fix an older server: `chmod -R a+rX /opt/log-stack/grafana && docker compose restart grafana`.

### Disk usage on a Nanode (25GB)
Loki retention is 30 days. On a heavily-attacked honeypot, log volume is significant. If Loki fills the disk, Docker stops writing and the stack goes unhealthy. Monitor with `df -h`; tune `ingestion_rate_mb` or `retention_period` in `loki/loki-config.yml`.

### Legacy `connect.py` / `deploy.py` / `test_loki.py` in this directory
Predecessors of `scripts/connect.py`, `scripts/redeploy.py`, `scripts/test_loki.py`. Use the root scripts instead — they read `honey-net.json` and target any server.
