# Honey-Net — Technical Reference

A proof-of-concept honeypot network for threat intelligence and attacker behavior research.

## System overview

Three components run on Ubuntu 24.04 LTS in Docker Compose, connected via a private Tailscale VPN. All hosts are defined in `honey-net.json` (single source of truth). Tailscale is the only path to real SSH (port 65022).

- **Honeypot servers** — VMs running honeypot service packages (Cowrie, MySQL, Dionaea) + a Vector sidecar. Ship logs to log-stack and captured malware to malware-catalog via the `malware-sender` addon.
- **Log-stack** — Grafana + Loki. Receives logs from honeypots and malware-catalog. Never exposed to the public internet.
- **Malware-catalog** — Collects, deduplicates (SHA-256), and enriches samples. Never exposed to the public internet.

## Security model

Honeypots are **untrusted by default** — they are actively attacked and expected to be compromised. The rest of the infrastructure is hardened to survive that compromise:

- **Container + VM isolation** — each honeypot service runs in a Docker container on its own Linode Nanode. A jailbreak stays within one VM.
- **Network segmentation** — all inter-host traffic goes over Tailscale; admin services bind to private Tailscale IPs only. Public ports (22, 3306, etc.) bind to the honeypot, never the host.
- **Auth** — Ed25519 SSH keys only, passwords disabled, real SSH on port 65022 (Tailscale-only). UFW + fail2ban on every host.
- **Immutable audit trail** — logs ship off-box continuously; catalog records are insert-only. A compromised honeypot cannot rewrite history.

See `server-config/CLAUDE.md` for hardening details.

## Key contracts

**`honey-net.json` is the single source of truth.** All root scripts read from it. Add a server entry with `name`, `type`, `ssh_key`, `ports`, `honeypots`; no Terraform or root-script changes needed.

**Self-describing packages.** New honeypots/addons require no root-level changes — behavior is declared inside the package directory and discovered at runtime.

**Hardcoded filesystem paths** (control plane and addons depend on these):
- Honeypot logs → `/opt/<server>/<honeypot>/volumes/logs/<honeypot>.json` (newline-delimited JSON)
- Malware samples → `/opt/<server>/<honeypot>/volumes/inbox/` (arbitrary filenames; `malware-sender` cleans up)

**Two log streams in Loki:**
- `{job="<honeypot>"}` — raw service events (full detail, for forensics)
- `{job="events", honeypot="<name>"}` — normalized cross-honeypot stream with unified event types (`connect`, `login`, `command`, `download`, `session_end`). See `honey-pots/CLAUDE.md` for the schema and per-honeypot VRL mappings.

**Malware-catalog contract:**
- Submission API dedupes by SHA-256; records are immutable once created.
- `static-analyzer` (YARA, IOCs, ssdeep) always runs. `intel-fetcher` (VirusTotal/MalwareBazaar) and `sandbox-submitter` (tria.ge) are opt-in via API keys in `.env`.
- See `malware-catalog/CLAUDE.md` for the worker queue pattern and DB design.

## Control plane

`honey.py` is the single entry point — a CLI launcher that discovers `scripts/*.py`, handles credentials upfront, threads state (`state.json`, IPs, `LOKI_HOST`) forward between dependent deploys, and exposes everything as either a menu or flag-based invocation. Scripts are independently runnable (`python scripts/<name>.py`) so the launcher never becomes a bottleneck. See README.md for the full script list and usage.

## Component map

| Path | Purpose | Detailed docs |
|------|---------|---------------|
| `honey-pots/` | Honeypot service packages (Cowrie, MySQL, Dionaea) | `honey-pots/CLAUDE.md` + per-honeypot subdirs |
| `addons/` | Sidecars (metadata extraction, malware submission) | `addons/CLAUDE.md` + per-addon subdirs |
| `malware-catalog/` | Sample catalog API, enrichment workers, web UI | `malware-catalog/CLAUDE.md` |
| `server-config/` | Shared host hardening (UFW, SSH, fail2ban) | `server-config/CLAUDE.md` |
| `log-stack/` | Grafana + Loki stack | `log-stack/CLAUDE.md` |
| `terraform/` | Infrastructure-as-code (Linode VMs) | `terraform/CLAUDE.md` |
| `lib/` | Shared Python library (config, ssh, packages, servers) | — |
| `scripts/` | Control plane scripts (provision, deploy, sync) | — |

## See README.md for

Quick start, prerequisites (Linode/Tailscale/SSH keys), provisioning and deployment procedures, re-deployment, log pulling, and adding a new honeypot server.
