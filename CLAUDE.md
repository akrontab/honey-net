# Honey-Net

A proof-of-concept honeypot network for threat intelligence and attacker behavior research.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Tailscale VPN                     │
│                                                      │
│  ┌──────────────────┐      ┌──────────────────────┐  │
│  │  cowrie-honeypot │─────▶│     log-stack        │  │
│  │                  │      │                      │  │
│  │  Cowrie (SSH)    │      │  Loki (log store)    │  │
│  │  Vector (shipper)│      │  Grafana (dashboards)│  │
│  │                  │      │                      │  │
│  │  Nanode $5/mo    │      │  Nanode $5/mo        │  │
│  └──────────────────┘      └──────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

- **cowrie-honeypot** — SSH honeypot on port 22, real SSH on port 65022. Captures attacker sessions, commands, and malware samples. Vector sidecar ships logs to Loki over Tailscale.
- **log-stack** — Grafana + Loki. Receives logs from all honeypots over Tailscale. Grafana is accessible only on the Tailscale network (not public internet).

All hosts run Ubuntu 24.04 LTS in Docker Compose. The Tailscale network ties them together regardless of hosting provider.

## Repos

| Folder | Purpose |
|--------|---------|
| `cowrie-honeypot/` | Honeypot host — Cowrie + Vector |
| `log-stack/` | Visualization host — Grafana + Loki |
| `terraform/` | Infrastructure — creates all hosts on Linode |

Each repo has its own `CLAUDE.md` with host-specific gotchas and commands.

## Prerequisites

Before deploying either host you need:

1. **SSH key pair** for each host — generated automatically by `setup-key.ps1` in each repo, or manually:
   ```powershell
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\cowrie-linode"
   ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\log-stack-linode"
   ```

2. **Tailscale account** — [tailscale.com](https://tailscale.com). Free tier covers this entire project.
   Generate an auth key for each new host:
   ```powershell
   .\gen-ts-key.ps1              # log-stack — non-ephemeral (survives reboots)
   .\gen-ts-key.ps1 -Ephemeral   # cowrie — ephemeral (auto-removed from tailnet on destroy)
   ```
   First run prompts for a Tailscale **API key** (Settings → Keys → Generate API key) and offers to save it to `~/.tailscale-apikey`. Subsequent runs print a fresh auth key ready to paste into `setup.sh`.

   Ephemeral nodes disappear from the tailnet automatically when the VM is destroyed — no manual cleanup in the Tailscale admin console needed.

3. **Linode API token** — cloud.linode.com → Profile → API Tokens → Create. Requires Read/Write access to Linodes.

## Provisioning with Terraform

Terraform creates both hosts and injects SSH keys automatically. Run once per environment.

```powershell
cd terraform
copy terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — add linode_token and root passwords
terraform init
terraform plan
terraform apply
cd ..
.\sync-ips.ps1    # caches IPs from terraform outputs into each repo's .server-ip
```

To destroy all infrastructure:
```powershell
cd terraform && terraform destroy
```

### Adding a second honeypot via Terraform

Add a new module block to `terraform/main.tf`:

```hcl
module "cowrie_2" {
  source     = "./modules/host"
  label      = "cowrie-honeypot-2"
  region     = var.region
  ssh_pubkey = file(pathexpand("~/.ssh/cowrie-linode.pub"))
  root_pass  = var.cowrie_root_pass
  tags       = ["honey-net", "cowrie"]
}
```

Then `terraform apply` and `.\sync-ips.ps1`.

## Deployment Order

Deploy log-stack first so its Tailscale IP is known before configuring Cowrie's Vector shipper.

### 1. Deploy log-stack

```powershell
cd log-stack
.\deploy.ps1           # copies deploy/ to server (IP read from .server-ip)
.\connect.ps1          # SSH in
```

On the server:
```bash
sudo bash /root/log-stack/setup/setup.sh
# Prompts for: Tailscale auth key, Grafana admin password
```

When setup completes it prints:
```
Tailscale IP : 100.x.x.x
Grafana      : http://100.x.x.x:3000
Loki         : http://100.x.x.x:3100
```

Note the Tailscale IP — you need it for the next step.

### 2. Deploy cowrie-honeypot

```powershell
cd cowrie-honeypot
.\deploy.ps1           # copies deploy/ to server
.\connect.ps1          # SSH in (port 22 before setup, 65022 after)
```

On the server:
```bash
sudo bash /root/cowrie-honeypot/setup/setup.sh
```

After setup, create the `.env` for Vector:
```bash
cp /opt/cowrie-honeypot/.env.example /opt/cowrie-honeypot/.env
nano /opt/cowrie-honeypot/.env
# Set LOKI_HOST to the Tailscale IP from step 1
```

Restart to bring Vector up with the correct target:
```bash
cd /opt/cowrie-honeypot && docker compose up -d
```

### 3. Verify logs are flowing

From your local machine:
```powershell
cd log-stack
.\test-loki.ps1       # pushes a test log line, confirms Tailscale + Loki are working
```

In Grafana (`http://<tailscale-ip>:3000`, admin / your password):
- Go to Explore → select Loki datasource
- Query: `{job="cowrie"}` — should show Cowrie events
- Query: `{job="auth"}` — should show host auth.log from the honeypot

## Re-deploying After Changes

```powershell
# Push updated files to a host
cd cowrie-honeypot
.\deploy.ps1 -PostSetup     # uses port 65022

cd log-stack
.\deploy.ps1 -PostSetup
```

Then on each server:
```bash
sudo bash /root/<project>/setup/setup.sh --redeploy
```

`--redeploy` syncs files from `/root/<project>/` to `/opt/<project>/` and runs `docker compose up -d` (with `--build` on cowrie). Skips all system provisioning steps. The `.env` is preserved.

## Adding a Second Honeypot

1. Add a new module block in `terraform/main.tf` (see Terraform section above) and run `terraform apply`.
2. Run `.\sync-ips.ps1` to pick up the new IP — or note it from the terraform output.
3. Deploy and provision it the same way as the first cowrie host.
4. Set `LOKI_HOST` in its `.env` to the same log-stack Tailscale IP.
5. Use a distinct `HONEYPOT_HOSTNAME` in `.env` (e.g., `cowrie-honeypot-2`) so logs from each host are labeled separately in Grafana.

## Logs and Samples (cowrie-honeypot)

```powershell
cd cowrie-honeypot
.\get-logs.ps1          # pull cowrie.json to logs/
.\get-downloads.ps1     # pull malware samples to downloads/
.\analyze-logs.ps1      # quick PowerShell summary
.\harvest-keys.ps1      # extract attacker SSH keys, push back to Cowrie
```

## Useful Server Commands

```bash
# cowrie-honeypot host
docker compose -f /opt/cowrie-honeypot/docker-compose.yml ps
docker compose -f /opt/cowrie-honeypot/docker-compose.yml logs -f cowrie
docker compose -f /opt/cowrie-honeypot/docker-compose.yml logs -f vector

# log-stack host
docker compose -f /opt/log-stack/docker-compose.yml ps
docker compose -f /opt/log-stack/docker-compose.yml logs -f loki
docker compose -f /opt/log-stack/docker-compose.yml logs -f grafana

# Tailscale status (either host)
tailscale status
tailscale ip -4
```
