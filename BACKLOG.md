# Backlog

Ideas and features to implement. Tell Claude "implement the next backlog item" to work through these one at a time. When starting on a new item plan first and prompt for any infomration needed for implementation. Then once all information is collected, start implementation.

## Pending

- [x] Alerting Phase 1 — detection-event contract + detector service + detection dashboard. Live on log-stack. See `docs/alerting-plan.md`.
- [ ] Alerting Phase 1 increment — first-seen registry in catalog + `novel_<type>` selector-novelty rules (rule class 4, ex-HASSH). See `docs/alerting-plan.md`.
- [ ] Alerting Phase 2 — notification dispatcher + first channel (Telegram), severity-routed. Secrets needed. See `docs/alerting-plan.md`.
- [ ] Dashboard overhaul — Hunt core: Credential intel + Download & infra intel on `meta_*`. See `docs/dashboard-overhaul-plan.md`.
- [ ] Nice to have later: multiple operators with thier own user accounts with sudo access for host management. Maintain keybased logins
- [ ] Update README and remove references to specific honeypots in logs
- [ ] HTTP honeypot phase 4 — TLS on :443 (self-signed cert). Add 443 to `mysql-ssh` `ports` in `honey-net.json`, open it in `honey-pots/http/deploy/setup/fragment.sh`, and serve TLS from the app. See `docs/http-honeypot-plan.md`.
- [ ] HTTP honeypot phase 5 — Grafana dashboard under `log-stack/deploy/grafana/provisioning/dashboards/`: top paths, top user-agents, credential attempts, uploads. See `docs/http-honeypot-plan.md`.

## Maybes

- [ ] Multiple cloud provider support with terraform

## Done

- [x] Dashboard overhaul — **Triage tier**: situational **Overview** on `{job="events"}` (`Triage/overview.json`, uid `triage-overview`), replaces `normalized-events` as the landing board; alert-state slot left for alerting Phase 1. Provisioning switched to tier folders. *Built + JSON-validated; live verification pending.* See `docs/dashboard-overhaul-plan.md`.
- [x] Dashboard overhaul — **Operate tier**: Fleet health re-keyed on `(honeypot, host)`, Host security (templated on `host`), Pipeline/ingest health (`Operate/*.json`). *Built + JSON-validated; live verification pending.* See `docs/dashboard-overhaul-plan.md`.
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
