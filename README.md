# honey-net

A proof-of-concept honeypot network for threat intelligence and attacker behavior research. Honeypot servers expose common services (SSH, Telnet, MySQL) to the public internet, capture attacker activity, and ship logs to a private Grafana/Loki stack over Tailscale VPN.

**Cost:** ~$10–15/mo on Linode Nanodes. **CLAUDE.md** has full technical details for every component.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Tailscale VPN                           │
│                                                                 │
│  ┌──────────────────────┐                                       │
│  │   honeypot server    │──┐  ┌──────────────────────────────┐  │
│  │  service(s) + Vector │  │  │          log-stack           │  │
│  │  Nanode $5/mo        │  ├─▶│  Loki · Grafana              │  │
│  └──────────────────────┘  │  │  Nanode $5/mo                │  │
│                            │  └──────────────────────────────┘  │
│  ┌──────────────────────┐  │                                    │
│  │   honeypot server    │──┘                                    │
│  │  service(s) + Vector │                                       │
│  │  Nanode $5/mo        │                                       │
│  └──────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
```

- **Honeypot servers** run one or more service packages (Cowrie SSH/Telnet, MySQL emulator) plus a Vector sidecar that ships logs to Loki over Tailscale. Public-facing.
- **Log-stack** runs Grafana + Loki. Receives logs from all honeypots. Never exposed to the public internet — Tailscale only.
- Real SSH on every host is port **65022**, Tailscale-only. Port 22 goes to the honeypot.

## Repo layout

```
honey-net/
  honey-pots/
    cowrie/          ← SSH/Telnet honeypot package
    mysql/           ← MySQL wire-protocol honeypot package
  server-config/     ← shared host hardening (UFW, SSH, fail2ban)
  log-stack/         ← gitignored, separate repo
  terraform/         ← gitignored, separate repo
  honey-net.json     ← server manifest (single source of truth)
  state.json         ← gitignored, written by sync_ips.py
  honey.py           ← interactive launcher for all commands
  deploy.py          ← first deploy (public IP, port 22)
  redeploy.py        ← update a live server (Tailscale, port 65022)
  connect.py         ← SSH into a server
  sync_ips.py        ← write IPs from Terraform + Tailscale to state.json
  get_logs.py        ← pull logs from a honeypot
  gen_ts_key.py      ← generate a Tailscale auth key
  _lib.py            ← shared utilities
  setup.ps1          ← one-time local setup (Windows)
  setup.sh           ← one-time local setup (macOS/Linux)
  requirements.txt
```

`honey-net.json` is the single source of truth for all servers. Adding a server entry is all that's needed — no changes to Terraform modules or root scripts required.

## Prerequisites

**1. Python environment** — run once after cloning:

```powershell
# Windows
.\setup.ps1
.venv\Scripts\activate
```
```bash
# macOS / Linux
./setup.sh
source .venv/bin/activate
```

**2. SSH key pairs** — one per server, path set in `honey-net.json`:
```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\log-stack-linode"
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\mysql-ssh-honeypot"
```

**3. Tailscale account** — [tailscale.com](https://tailscale.com) (free tier). Generate auth keys before each deploy:
```
python gen_ts_key.py              # log-stack and other backends
python gen_ts_key.py --ephemeral  # honeypot servers (auto-removed on destroy)
```

**4. Linode API token** — cloud.linode.com → Profile → API Tokens → Create (Read/Write Linodes scope).

## Deployment order

### 1. Provision infrastructure

```powershell
cd terraform
copy terraform.tfvars.example terraform.tfvars
# Add linode_token to terraform.tfvars
terraform init && terraform apply
cd ..
python sync_ips.py
```

### 2. Deploy log-stack first

```
python deploy.py --server log-stack
python connect.py --server log-stack --pre-setup
```
```bash
sudo bash /root/log-stack/setup.sh
# Prompts for: Tailscale auth key, Grafana admin password
```

After setup prints the Tailscale IP, capture it:
```
python sync_ips.py
```

### 3. Deploy honeypots

```
python gen_ts_key.py --ephemeral
python deploy.py --server mysql-ssh
python connect.py --server mysql-ssh --pre-setup
```
```bash
sudo bash /root/mysql-ssh/setup.sh
# Prompts for: Tailscale auth key, Loki IP (pre-filled from state.json), hostname
```

```
python sync_ips.py
```

## Common commands

All commands support interactive mode (no flags) via `python honey.py`, or direct flags:

```
python connect.py --server mysql-ssh       # SSH in (Tailscale required)
python redeploy.py --server mysql-ssh      # push updates + restart stack
python get_logs.py --server mysql-ssh      # pull cowrie.json + mysql-honeypot.json
python sync_ips.py                         # refresh state.json after any IP change
```

## Adding a honeypot server

1. Add an entry to `honey-net.json` with `name`, `ssh_key`, `honeypots`, `ports`.
2. Generate an SSH key pair for it.
3. Run `terraform apply` — the VM is created automatically.
4. Follow the deployment steps above.

No changes to `terraform/main.tf` or any root script are needed.

## Currently deployed honeypots

| Package | Protocols | Ports | Captures |
|---------|-----------|-------|---------|
| cowrie | SSH, Telnet | 22, 23 | Sessions, commands, malware downloads, attacker SSH keys |
| mysql | MySQL | 3306 | Credentials (username), SQL queries, database enumeration |
