# Backlog

Ideas and features to implement. Tell Claude "implement the next backlog item" to work through these one at a time. When starting on a new item plan first and prompt for any infomration needed for implementation. Then once all information is collected, start implementation.

## Pending

- [ ] Dashboard overhaul — **Triage tier**: new situational **Overview** on `{job="events"}` (event volume by `event_type`/`protocol`/sensor, live activity feed, alert-state slot left for the alerting Phase 1 detection panel). Becomes the landing dashboard, replacing `normalized-events`. Provisioned under a `Triage` Grafana folder. See `docs/dashboard-overhaul-plan.md` (Q1=tier folders, Q3=fresh Overview — resolved).
- [ ] Dashboard overhaul — **Operate tier**: Fleet/sensor health re-keyed on `(honeypot, host)` (fixes the two-host merge in `sensor-health`); Host security (from `host-security`); Pipeline/ingest health (Loki/Vector throughput, disk). Provisioned under an `Operate` folder. See `docs/dashboard-overhaul-plan.md`.
- [ ] Nice to have later: multiple operators with thier own user accounts with sudo access for host management. Maintain keybased logins
- [ ] Update README and remove references to specific honeypots in logs
- [ ] HTTP honeypot phase 4 — TLS on :443 (self-signed cert). Add 443 to `mysql-ssh` `ports` in `honey-net.json`, open it in `honey-pots/http/deploy/setup/fragment.sh`, and serve TLS from the app. See `docs/http-honeypot-plan.md`.
- [ ] HTTP honeypot phase 5 — Grafana dashboard under `log-stack/deploy/grafana/provisioning/dashboards/`: top paths, top user-agents, credential attempts, uploads. See `docs/http-honeypot-plan.md`.

## Maybes

- [ ] Multiple cloud provider support with terraform

## Done

- [x] Backup and restore scripts for logs, inbox, and malware catalog (`scripts/backup.py`, `scripts/restore.py`)
- [x] Create dashboard for normalized logs
  - [x] Refactor the campaign dashboard (download panels now use `{job="events"}`, covers all honeypots)
  - [x] General log for detections and file downloads (`normalized-events.json`, uid `normalized-events`)
- [x] Tailscale clean up scripts for old machines that are no longer on the network. Sync with terraform state
- [x] User segmentation on all hosts. STOP RUNNING EVERYTHING AS ROOT!
  - [x] Docker is run with a non-root user on honeypot container hosts
  - [x] Log-stack docker processes are run with a non-root user
  - [x] Malware catalog docker processes are run with non-root users
  - [x] Remote managemnt of hosts (ssh) still uses root and still uses key based auth
  - [x] non-root users should not be accessed directly with ssh. Allows for easy auditing and intrusion detection
