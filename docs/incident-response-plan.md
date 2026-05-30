# Failure Modes & Incident Response — Plan

Catalogs how honey-net hosts and network can fail, how each is detected, and the
response playbook. Spans honeypot hosts, backend hosts (`log-stack`,
`malware-catalog`), the network/Tailscale layer, and the control-plane /
management host. Graduates from the **Trust & audit integrity** and **Operational
maturity** themes in `docs/!VISION.md`.

This is a *plan* — it inventories the modes and sketches the responses; the
per-scenario runbooks and alerting graduate to `BACKLOG.md` from here.

## Stance

- **Honeypots are cattle.** They are untrusted and ephemeral
  (`tailscale_ephemeral: true`). Compromise is an *expected event*, not a
  disaster — the response is **capture evidence, then destroy and reprovision**,
  not forensic cleanup-in-place. Logs already shipped off-box, so the trail
  survives the host.
- **Backends are pets.** `log-stack` and `malware-catalog` hold the system of
  record (immutable audit trail, malware catalog). They are never publicly
  exposed; response prioritizes **integrity and restore** over speed.
- **The audit trail outlives the host.** Continuous off-box log shipping means a
  compromised honeypot can't rewrite history — post-mortems run on Loki even if
  the source VM is gone.

## Failure modes & response

### Honeypot hosts

| Failure | Detection | Response |
|---|---|---|
| Service / container crash | Grafana stream gap; `check_logs.py` | `docker compose restart <svc>`; if the host is unhealthy, reprovision. |
| Disk full (25 GB Nanode) | `check_disk.py` | Prune images/old logs; captured samples already shipped to the catalog, so local loss is acceptable; if recurring, add log rotation or a bigger plan. |
| Host / container compromise (expected) | Anomalous egress, fail2ban spikes, host metrics | Treat as data, not emergency: confirm logs shipped, then `terraform destroy` + `provision.py` to rebuild fresh. The ephemeral Tailscale node auto-cleans on destroy. |
| Log shipping stopped (Vector) | Stream present then silent while host is up | **Known mode:** a stale Vector checkpoint past EOF after a log-volume recreate ships nothing silently. Fix by renaming the source key + `device_and_inode` fingerprinting (see internal notes). |
| Public-port regression (host port exposed) | External scan / UFW audit | Re-assert UFW; honeypot ports must bind to the container, never the host. |

### Backend hosts (`log-stack`, `malware-catalog`)

| Failure | Detection | Response |
|---|---|---|
| Loki down | No data in Grafana; honeypot Vectors backpressure/buffer | Restart Loki; check disk. Vectors retry, so a short outage is lossless. |
| Grafana down | Dashboards unreachable | Restart; data is intact in Loki. |
| Catalog API down | `malware-sender` submissions fail | Restart; the shared `inbox/` holds samples until it returns — they accumulate safely, nothing is dropped. |
| SQLite lock / corruption | `database is locked` under concurrent writes (no WAL mode) | Retry transient locks; if corrupt, restore from backup. Revisit WAL if write rate grows (see `malware-catalog/CLAUDE.md`). |
| Backend compromise | Crown-jewel breach indicators | Rotate the fleet anchor + Tailscale keys; restore catalog/logs from backup; rebuild the host; post-mortem from the immutable off-box logs. |
| Disk full / sample-store growth | `check_disk.py`; catalog size | Prune/rotate; offload or archive old samples. |

### Network / Tailscale

| Failure | Detection | Response |
|---|---|---|
| Tailscale outage | No admin service or :65022 reachable | Break-glass via provider console; honeypots keep capturing locally and Vectors queue until the tailnet returns. |
| Auth-key expiry | New/rebooted node won't join the tailnet | Regenerate (`gen_ts_key.py`); use non-ephemeral keys for backends, ephemeral for honeypots. |
| Provider / region outage | Hosts unreachable or down | Honeypots: reprovision elsewhere. Backends: restore from backup into a new region. |
| UFW / sshd lockout on :65022 | Can't SSH even over the tailnet | Provider console break-glass; fix UFW/sshd. (This is why setup verifies key login *before* hardening.) |

### Control plane / management host

| Failure | Detection | Response |
|---|---|---|
| Management host down | Operators lose the access funnel | Break-glass via provider console; the mgmt host is reprovisionable from config. |
| Single anchor / CA-key compromise | The rotate-at-will scenario | Rotate the one anchor, re-trust the fleet, KRL old certs — the property `docs/multi-operator-plan.md` is built to deliver. |
| `state.json` drift | Scripts target stale IPs | `sync_ips.py` to reconcile from Terraform + Tailscale. |

## Playbooks (the high-impact scenarios)

1. **Honeypot compromise** → confirm logs shipped → snapshot any captured samples
   → `terraform destroy` the VM → `provision.py` to rebuild fresh → verify streams
   resume in Grafana.
2. **Backend compromise** → isolate (tighten UFW / pull from tailnet) → rotate
   fleet anchor + Tailscale keys → restore from backup → rebuild host →
   post-mortem from immutable Loki logs.
3. **Lost admin access (Tailscale / SSH)** → provider console break-glass →
   diagnose UFW / sshd / Tailscale → restore connectivity → re-verify :65022.
4. **Anchor / key compromise** → rotate the single anchor → re-push trust to the
   fleet → KRL/expire outstanding certs → audit the exposure window in
   `{job="auth"}`.
5. **Data-pipeline stall (no logs)** → check Vector checkpoint state → check Loki
   health and disk → confirm Tailscale path.

## Relies on (preconditions)

- Continuous off-box log shipping (already in place) so post-mortems survive host loss.
- Backups: `scripts/backup.py` / `scripts/restore.py` for logs, inbox, and the malware catalog (`BACKLOG.md` Done).
- Health checks: `check_logs.py`, `check_disk.py`, `test_loki.py`.
- Ephemeral honeypots (`tailscale_ephemeral`) so destroy/rebuild is clean.
- A provider-specific break-glass console (LISH on Linode; differs per cloud).
- The single rotatable trust anchor from `docs/multi-operator-plan.md`.

## Open questions

- **Alerting** — detection today is manual via the `check_*` scripts. Wire Grafana
  alerts for stream gaps, disk pressure, and fail2ban spikes (ties to the
  **Operationalizing the intel** theme).
- **RTO / RPO for backends** — how much catalog/log loss is acceptable? Sizes the
  backup cadence.
- **Auto-rebuild** — should a honeypot-compromise signal trigger automated
  destroy/reprovision (self-healing, **Operational maturity**), or stay manual?

## Graduation to BACKLOG

- [ ] Per-scenario runbook docs (exact steps + commands) for the five playbooks
- [ ] Grafana alerts for the key detections (stream gap, disk, auth anomalies)
- [ ] Verify backup/restore against a simulated backend loss
- [ ] Document per-provider break-glass (LISH + others)
- [ ] Tabletop test: honeypot compromise + anchor rotation, end to end
