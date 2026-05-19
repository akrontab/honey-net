# Honey-Net

A proof-of-concept honeypot network for threat intelligence and attacker behavior research.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Tailscale VPN                       │
│                                                          │
│  ┌──────────────────┐     ┌──────────────────────────┐   │
│  │  cowrie-honeypot │────▶│       log-stack          │   │
│  │  Cowrie (SSH)    │     │                          │   │
│  │  Vector (shipper)│     │  Loki (log store)        │   │
│  │  Nanode $5/mo    │     │  Grafana (dashboards)    │   │
│  └──────────────────┘     │                          │   │
│                           │  Nanode $5/mo            │   │
│  ┌──────────────────┐     └──────────────────────────┘   │
│  │  mysql-honeypot  │────▶             ▲                  │
│  │  MySQL :3306     │                                    │
│  │  Vector (shipper)│                                    │
│  │  Nanode $5/mo    │                                    │
│  └──────────────────┘                                    │
└──────────────────────────────────────────────────────────┘
```

- **cowrie-honeypot** — SSH honeypot on port 22, Telnet on port 23, real SSH on port 65022 (Tailscale only). Captures sessions, commands, and malware samples.
- **mysql-honeypot** — MySQL wire-protocol honeypot on port 3306, real SSH on port 65022 (Tailscale only). Logs credentials and SQL queries.
- **log-stack** — Grafana + Loki. Receives logs from all honeypots over Tailscale. Never exposed to the public internet.

All hosts run Ubuntu 24.04 LTS in Docker Compose. The Tailscale VPN connects them and is the only path to real SSH on any host.

## Repo layout

```
honey-net/                    ← this repo (control plane)
  honey-pots/
    cowrie/                   ← cowrie service package
    mysql/                    ← mysql service package
  server-config/              ← shared host hardening
  log-stack/                  ← gitignored, separate repo
  cowrie-honeypot/            ← gitignored, separate repo (legacy)
  mysql-honeypot/             ← gitignored, separate repo (legacy)
  terraform/                  ← gitignored, separate repo
  honey-net.json              ← authored server manifest
  state.json                  ← gitignored, written by sync-ips.ps1
  deploy.ps1                  ← first deploy (port 22)
  redeploy.ps1                ← update a live server (port 65022, Tailscale)
  connect.ps1                 ← SSH into a server
  sync-ips.ps1                ← write IPs from terraform + Tailscale to state.json
  get-logs.ps1                ← pull logs from a honeypot
  gen-ts-key.ps1              ← generate a Tailscale auth key
```

`honey-net.json` is the single source of truth for all servers. All root scripts read from it. See `DESIGN.md` for the full architecture.

Each component has its own `CLAUDE.md`:

| Path | Contents |
|------|----------|
| `honey-pots/cowrie/CLAUDE.md` | Cowrie protocol, log paths, gotchas |
| `honey-pots/mysql/CLAUDE.md` | MySQL emulator, event types, gotchas |
| `server-config/CLAUDE.md` | Base setup.sh steps, Tailscale SSH restriction |
| `log-stack/CLAUDE.md` | Grafana/Loki config, LogQL queries |
| `terraform/CLAUDE.md` | Terraform usage, for_each design, state keys |

## Prerequisites

Before deploying any server:

1. **SSH key pair** for each server — path set in `honey-net.json` (`ssh_key` field):
   ```powershell
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\log-stack-linode"
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\cowrie-linode"
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\mysql-linode"
   ```

2. **Tailscale account** — [tailscale.com](https://tailscale.com). Free tier covers this entire project.
   Generate an auth key for each new host before running `setup.sh`:
   ```powershell
   .\gen-ts-key.ps1              # backend servers — non-ephemeral (survives reboots)
   .\gen-ts-key.ps1 -Ephemeral   # honeypot servers — auto-removed from tailnet on destroy
   ```
   First run prompts for a Tailscale **API key** (tailscale.com → Settings → Keys → Generate API key)
   and saves it to `~/.tailscale-apikey`. Subsequent runs print a fresh auth key.

3. **Linode API token** — cloud.linode.com → Profile → API Tokens → Create.
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
.\sync-ips.ps1    # reads terraform output + Tailscale API, writes state.json
```

To destroy all infrastructure:
```powershell
cd terraform && terraform destroy
```

### Adding a new server

1. Add an entry to `honey-net.json` with `name`, `type`, `ssh_key`, `ports`, and `honeypots`.
2. Generate an SSH key pair for the new server.
3. If it's a new honeypot type, create `honey-pots/<name>/` with the standard layout.
4. Run `terraform apply` — the new VM is created automatically.
5. Run `.\sync-ips.ps1` to add the new server to `state.json`.

No changes to `terraform/main.tf` are needed.

## Deployment order

Deploy log-stack first — its Tailscale IP is required by Vector on every honeypot.

### 1. Deploy log-stack

> **Note:** `log-stack/` is a separate git repo (gitignored here). Clone it alongside
> this repo before running `deploy.ps1`. The root script copies from `log-stack/deploy/`.

```powershell
.\deploy.ps1 -Server log-stack
.\connect.ps1 -Server log-stack   # connects on port 22 (pre-setup)
```
```bash
sudo bash /root/log-stack/setup.sh
# Prompts for: Tailscale auth key, Grafana admin password
```

When setup completes it prints the Tailscale IP:
```
Tailscale IP : 100.x.x.x
Grafana      : http://100.x.x.x:3000
Loki         : http://100.x.x.x:3100
```

**Run `sync-ips.ps1` now** — this captures the log-stack Tailscale IP into `state.json`.
Honeypot `setup.sh` reads that IP from `state.json` to configure Vector. If you skip this
step, you will have to set `LOKI_HOST` manually in each honeypot's `.env` after the fact.

```powershell
.\sync-ips.ps1
```

### 2. Deploy honeypots

For each honeypot server, generate a Tailscale auth key first:
```powershell
.\gen-ts-key.ps1 -Ephemeral   # ephemeral — node auto-removes when VM is destroyed
```

Then deploy and provision:
```powershell
.\deploy.ps1 -Server mysql-ssh   # assembles package (cowrie + mysql), SCPs to server
.\connect.ps1 -Server mysql-ssh  # connects on port 22 (pre-setup)
```
```bash
sudo bash /root/mysql-ssh/setup.sh
# Prompts for: Tailscale auth key, Loki Tailscale IP (pre-filled from state.json), honeypot hostname
```

After `setup.sh` completes, port 22 is closed and SSH moves to port 65022 on the
Tailscale interface only.

Run `sync-ips.ps1` a final time to capture the honeypot's Tailscale IP — needed by
`redeploy.ps1` and `connect.ps1` going forward:
```powershell
.\sync-ips.ps1
```

### 3. Verify logs are flowing

```powershell
# Push a test log line to Loki (requires Tailscale running locally)
cd log-stack
.\test-loki.ps1
```

In Grafana (`http://<tailscale-ip>:3000`):
- `{job="cowrie"}` — Cowrie events
- `{job="mysql"}` — MySQL credential and query events
- `{job="auth"}` — host auth.log from any honeypot
- `{job="malware"}` — YARA analyzer hits from Cowrie

## Re-deploying after changes

```powershell
.\redeploy.ps1 -Server mysql-ssh   # Tailscale required
.\redeploy.ps1 -Server log-stack
```

`redeploy.ps1` copies updated files to the server via Tailscale (port 65022) and runs
`docker compose up --build -d`. Does not touch system configuration. The `.env` is preserved.

## Pulling logs

```powershell
.\get-logs.ps1 -Server mysql-ssh   # saves cowrie.json + mysql-honeypot.json to logs/mysql-ssh/
```

Cowrie-specific scripts in the `cowrie-honeypot/` folder (separate repo) still work for
deeper analysis — `analyze-logs.ps1`, `harvest-keys.ps1`, `get-downloads.ps1`.

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
