# Honey-Net — Technical Reference

Proof-of-concept honeypot network for threat intelligence. Three host types run Ubuntu 24.04 LTS in Docker Compose, connected via Tailscale VPN.

## Security model

Honeypots are **untrusted by default** — actively attacked and expected to be compromised. The rest of the infrastructure is hardened to survive that:

- **Container + VM isolation** — each honeypot service runs in Docker on its own Linode Nanode; a jailbreak stays within one VM.
- **Network segmentation** — all inter-host traffic goes over Tailscale; admin services bind to Tailscale IPs only. Public ports bind to the honeypot container, never the host.
- **Auth** — Ed25519 SSH keys only, passwords disabled, real SSH on port 65022 (Tailscale-only). UFW + fail2ban on every host.
- **Immutable audit trail** — logs ship off-box continuously; catalog records are insert-only. A compromised honeypot cannot rewrite history.

See `server-config/CLAUDE.md` for hardening details.

## Key contracts

**`honey-net.json` is the single source of truth.** All root scripts read from it. Add a server entry with `name`, `type`, `ssh_key`, `ports`, `honeypots`; no Terraform or root-script changes needed.

**Self-describing packages.** New honeypots/addons require no root-level changes — behavior is declared inside the package directory and discovered at runtime.

**Hardcoded filesystem paths** (control plane and addons depend on these):
- Honeypot logs → `/opt/<server>/<honeypot>/volumes/logs/<honeypot>.json` (newline-delimited JSON)
- Malware samples → `/opt/<server>/<honeypot>/volumes/inbox/` (`malware-sender` cleans up)

**Two log streams in Loki:**
- `{job="<honeypot>"}` — raw service events (full detail, for forensics)
- `{job="events", honeypot="<name>"}` — normalized stream with unified event types (`connect`, `login`, `command`, `download`, `session_end`). See `honey-pots/CLAUDE.md` for schema and VRL mappings.

**Malware-catalog:** dedupes by SHA-256; records immutable once created. `static-analyzer` (YARA, IOCs, ssdeep) always runs; `intel-fetcher` (VirusTotal/MalwareBazaar) and `sandbox-submitter` (tria.ge) are opt-in via `.env` API keys. See `malware-catalog/CLAUDE.md`.

## Control plane

`honey.py` is the single entry point — has a hardcoded `COMMANDS` list mapping names to modules in `scripts/`; adding a new script requires a manual entry there. Handles credentials upfront, threads state (`state.json`, IPs, `LOKI_HOST`) between dependent deploys, exposes everything as a menu or flag-based invocation. Scripts are independently runnable (`python scripts/<name>.py`).

## Component map

| Path | Purpose | Docs |
|------|---------|------|
| `honey-pots/` | Honeypot packages (Cowrie, MySQL, Dionaea) | `honey-pots/CLAUDE.md` |
| `addons/` | Sidecars (metadata extraction, malware submission) | `addons/CLAUDE.md` |
| `malware-catalog/` | Sample catalog API, enrichment workers, web UI | `malware-catalog/CLAUDE.md` |
| `server-config/` | Shared host hardening (UFW, SSH, fail2ban) | `server-config/CLAUDE.md` |
| `log-stack/` | Grafana + Loki | `log-stack/CLAUDE.md` |
| `terraform/` | Infrastructure-as-code (Linode VMs) | `terraform/CLAUDE.md` |
| `lib/` | Shared Python library (config, ssh, packages, servers) | — |
| `scripts/` | Control plane scripts (provision, deploy, sync) | — |
| `docs/` | Architecture & planning prose | `!DESIGN.md`, `!VISION.md`, plan files |
