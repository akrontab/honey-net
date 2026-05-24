# Honey-Net

A proof-of-concept honeypot network for threat intelligence and attacker behavior research.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Tailscale VPN                           │
│                                                                 │
│  ┌──────────────────────┐                                       │
│  │   honeypot server    │──┐  ┌──────────────────────────────┐  │
│  │  service(s) + Vector │  │  │          log-stack           │  │
│  │  Nanode $5/mo        │  ├─▶│                              │  │
│  └──────────────────────┘  │  │  Loki (log store)            │  │
│                            │  │  Grafana (dashboards)        │  │
│  ┌──────────────────────┐  │  │                              │  │
│  │   honeypot server    │──┘  │  Nanode $5/mo                │  │
│  │  service(s) + Vector │     └──────────────────────────────┘  │
│  │  Nanode $5/mo        │                                       │
│  └──────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
```

- **honeypot servers** — One or more VMs, each running one or more honeypot service packages (e.g. Cowrie, MySQL) plus a Vector sidecar that ships logs to Loki over Tailscale. Real SSH on port 65022 (Tailscale only). Defined by `honey-net.json`.
- **log-stack** — Grafana + Loki. Receives logs from all honeypots over Tailscale. Never exposed to the public internet.

All hosts run Ubuntu 24.04 LTS in Docker Compose. The Tailscale VPN connects them and is the only path to real SSH on any host.

## Repo layout

```
honey-net/                    ← this repo (control plane)
  honey-pots/
    cowrie/                   ← cowrie honeypot package
    mysql/                    ← mysql honeypot package
  addons/
    metadata/                 ← metadata extractor addon (log → inbox sidecars)
    malware-sender/           ← malware-sender addon (inbox → malware catalog)
  server-config/              ← shared host hardening
  log-stack/                  ← Grafana + Loki stack
  terraform/                  ← infrastructure-as-code
  honey-net.json              ← authored server manifest
  state.json                  ← gitignored, written by sync_ips.py
  requirements.txt            ← Python dependencies (requests)
  setup.ps1                   ← one-time local setup (Windows)
  setup.sh                    ← one-time local setup (macOS/Linux)
  honey.py                    ← interactive launcher for all control scripts
  provision.py                ← end-to-end provisioning (terraform + server setup)
  redeploy.py                 ← update a live server (port 65022, Tailscale)
  connect.py                  ← SSH into a server
  sync_ips.py                 ← write IPs from terraform + Tailscale to state.json
  get_logs.py                 ← pull logs from a honeypot
  gen_ts_key.py               ← generate a Tailscale auth key
  check_ssh_keys.py           ← check / generate SSH keys for all servers
  check_logs.py               ← check log stream freshness in Loki
  check_disk.py               ← check disk usage on all servers (25 GB Nanode limit)
  test_loki.py                ← push a test log to Loki to verify the stack
  test_honeypot.py            ← run smoke tests for a honeypot type
  lib/                        ← shared library (config, ssh, color, package, server, files)
  _lib.py                     ← backward-compat re-export shim for honey-pots/*/test.py
```

`honey-net.json` is the single source of truth for all servers. All root scripts read from it. See `DESIGN.md` for the full architecture.

Each component has its own `CLAUDE.md`:

| Path | Contents |
|------|----------|
| `honey-pots/cowrie/CLAUDE.md` | Cowrie protocol, log paths, gotchas |
| `honey-pots/mysql/CLAUDE.md` | MySQL emulator, event types, gotchas |
| `addons/CLAUDE.md` | Addon package structure, shared inbox, fragment order |
| `addons/metadata/CLAUDE.md` | Sidecar schema, log formats, offset tracking |
| `addons/malware-sender/CLAUDE.md` | Submission flow, CLEAN_UP behaviour, gotchas |
| `server-config/CLAUDE.md` | Base setup.sh steps, Tailscale SSH restriction |
| `log-stack/CLAUDE.md` | Grafana/Loki config, LogQL queries |
| `terraform/CLAUDE.md` | Terraform usage, for_each design, state keys |

## Prerequisites

Before deploying any server:

1. **Python environment** — run once after cloning, before any other script:
   ```powershell
   # Windows
   .\setup.ps1
   .venv\Scripts\activate
   ```
   ```bash
   # macOS / Linux
   chmod +x setup.sh
   ./setup.sh
   source .venv/bin/activate
   ```
   This creates `.venv` and installs `requests`. All `python *.py` commands below
   assume the venv is active.

   Alternatively, use the interactive launcher for all commands:
   ```
   python honey.py
   ```

2. **SSH key pair** for each server — path set in `honey-net.json` (`ssh_key` field):
   ```powershell
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\log-stack-linode"
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\mysql-ssh-honeypot"
   ```

3. **Tailscale account** — [tailscale.com](https://tailscale.com). Free tier covers this entire project.
   Generate an auth key for each new host before running `setup.sh`:
   ```
   python gen_ts_key.py              # backend servers — non-ephemeral (survives reboots)
   python gen_ts_key.py --ephemeral  # honeypot servers — auto-removed from tailnet on destroy
   ```
   First run prompts for a Tailscale **API key** (tailscale.com → Settings → Keys → Generate API key)
   and saves it to `~/.tailscale-apikey`. Subsequent runs print a fresh auth key.

4. **Linode API token** — cloud.linode.com → Profile → API Tokens → Create.
   Requires Read/Write Linodes and Read Only Events scopes.

## Provisioning with Terraform

Terraform reads `honey-net.json` directly — adding a server entry is the only change needed.
Root passwords are auto-generated and stored in Terraform state.

```powershell
cd terraform
copy terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — add linode_token (and optionally region)
terraform init
terraform plan
terraform apply
cd ..
python sync_ips.py    # reads terraform output + Tailscale API, writes state.json
```

To destroy all infrastructure:
```powershell
cd terraform && terraform destroy
```

### Adding a new server

1. Add an entry to `honey-net.json` with `name`, `type`, `ssh_key`, `ports`, and `honeypots`.
2. Generate an SSH key pair for the new server.
3. If it's a new honeypot type, create `honey-pots/<name>/` with the standard layout.
4. Run `python provision.py --server <name>` — creates the VM via Terraform and runs full setup.

No changes to `terraform/main.tf` are needed.

## Deployment order

Deploy log-stack first — its Tailscale IP is required by Vector on every honeypot.

### 1. Deploy log-stack

```
python provision.py --server log-stack
```

Prompts for Tailscale API key (saved to `~/.tailscale-apikey`), Grafana admin password,
then runs end-to-end: waits for SSH, generates Tailscale auth key, SCPs files, runs
`setup.sh`, polls Tailscale until the node registers, and writes the Tailscale IP to
`state.json`.

If the run is interrupted and restarted, servers that already have a `tailscale_ip` in
`state.json` are skipped (prompts to confirm). Use `--force` to reprovision them without
the prompt.

### 2. Deploy honeypots

```
python provision.py --server mysql-ssh
```

Same flow. `provision.py` reads `LOKI_HOST` from `state.json` (set in step 1) and passes
it to `setup.sh` automatically. After setup completes, port 22 is closed and SSH moves
to port 65022 on the Tailscale interface only.

### 3. Verify logs are flowing

```
# Push a test log line to Loki (requires Tailscale running locally)
python test_loki.py
```

In Grafana (`http://<tailscale-ip>:3000`):
- `{job="cowrie"}` — Cowrie events
- `{job="mysql"}` — MySQL credential and query events
- `{job="auth"}` — host auth.log from the honeypot
- `{job="malware"}` — YARA analyzer hits from Cowrie

## Re-deploying after changes

```
python redeploy.py --server mysql-ssh   # Tailscale required
python redeploy.py --server log-stack
```

`redeploy.py` copies updated files to the server via Tailscale (port 65022) and runs
`docker compose up -d`. Does not touch system configuration. The `.env` is preserved.

## Pulling logs

```
python get_logs.py --server mysql-ssh   # saves cowrie.json + mysql-honeypot.json to logs/mysql-ssh/
```

## Useful server commands

```bash
# On mysql-ssh (runs both cowrie and mysql honeypots)
docker compose -f /opt/mysql-ssh/docker-compose.yml ps
docker compose -f /opt/mysql-ssh/docker-compose.yml logs -f cowrie
docker compose -f /opt/mysql-ssh/docker-compose.yml logs -f mysql-honeypot
docker compose -f /opt/mysql-ssh/docker-compose.yml logs -f vector

# On log-stack
docker compose -f /opt/log-stack/docker-compose.yml ps
docker compose -f /opt/log-stack/docker-compose.yml logs -f loki
docker compose -f /opt/log-stack/docker-compose.yml logs -f grafana

# Tailscale (any host)
tailscale status
tailscale ip -4
```
