# honey-net

A proof-of-concept honeypot network for threat intelligence and attacker behavior research. Honeypot servers expose common services (SSH, Telnet, MySQL) to the public internet, capture attacker activity, and ship logs to a private Grafana/Loki stack over Tailscale VPN.

**Cost:** ~$10–15/mo on Linode Nanodes. **CLAUDE.md** has full technical details for every component.

## Quick start

Accounts needed: [Linode](https://linode.com) (API token) · [Tailscale](https://tailscale.com) (API key, free tier)

**1. Clone and set up**
```powershell
git clone https://github.com/akrontab/honey-net
cd honey-net
.\setup.ps1                  # macOS/Linux: ./setup.sh
.venv\Scripts\activate
python honey.py check-keys   # generates any missing SSH key pairs
```

**2. Provision all servers**
```
python honey.py
```
Select **provision**. Prompts for credentials upfront (Linode token, Tailscale API key,
Grafana password), then provisions every server in dependency order — backends first
(log-stack → malware-catalog), then honeypots — threading `LOKI_HOST` and `CATALOG_URL`
forward automatically.

**3. Verify**
```
python honey.py
```
Select **logs** to pull log files locally. Open Grafana at `http://<log-stack-tailscale-ip>:3000` — raw streams appear under `{job="cowrie"}`, `{job="mysql"}`, `{job="dionaea"}`; the normalised cross-honeypot stream is `{job="events"}`.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                Tailscale VPN                                 │
│                                                                              │
│  ┌──────────────────────┐     ┌──────────────────────────────────────────┐   │
│  │   honeypot server    │──┐  │               log-stack                  │   │
│  │  service(s) + Vector │  ├─▶│  Loki · Grafana · Nanode $5/mo           │   │
│  │  Nanode $5/mo        │  │  └──────────────────────────────────────────┘   │
│  └──────────────────────┘  │                                                 │
│                            │  ┌──────────────────────────────────────────┐   │
│                            └─▶│            malware-catalog               │   │
│                               │  ui (nginx) · API · SQLite               │   │
│                               │  Nanode $5/mo                            │   │
│                               └──────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Honeypot servers** run one or more service packages (Cowrie SSH/Telnet, MySQL emulator) plus a Vector sidecar that ships logs to Loki over Tailscale. Public-facing.
- **Log-stack** runs Grafana + Loki. Receives logs from all honeypots. Never exposed to the public internet — Tailscale only.
- **Malware-catalog** receives malware samples from honeypots running the `malware-sender` addon. Deduplicates by SHA-256. Web UI + REST API served via nginx, API backend internal-only.
- Real SSH on every host is port **65022**, Tailscale-only. Port 22 goes to the honeypot.

## Design

> **Deeper reading in `docs/`:** [`!DESIGN.md`](docs/!DESIGN.md) explains the
> package model and data flows; [`!VISION.md`](docs/!VISION.md) covers where the
> project is headed; deep single-initiative plans (e.g.
> [`aws-eks-migration.md`](docs/aws-eks-migration.md),
> [`http-honeypot-plan.md`](docs/http-honeypot-plan.md)) live there too.

**Cheaper Than Starbucks™** — The full infrastructure runs on Linode Nanodes at $5/mo each. Services are chosen for low resource overhead so the whole network costs less than a coffee run.

**Swappable components** — No component is load-bearing in a way that locks the rest of the system in. Vector is the abstraction layer between honeypots and the log backend — honeypots write to files, Vector ships them, and only the sink config changes when the backend does.

**Isolation** — Honeypots are explicitly untrusted environments. Docker isolates each honeypot process from the host OS. Admin services (Grafana, Loki, malware-catalog) are bound to a private Tailscale IP and never exposed to the public internet. Each honeypot runs on its own VM so a compromise stays contained. Host hardening (UFW, SSH key-only auth, fail2ban) is applied uniformly at deploy time.

**Self-describing packages** — Adding a new honeypot or addon requires no changes to any root script. Every behavior the control plane needs (log paths, build requirements, provisioning steps) is declared inside the package itself. Root scripts discover these properties at runtime by reading from the package directory.

## Repo layout

```
honey-net/
├── honey-pots/
│   ├── cowrie/               ← SSH/Telnet honeypot package
│   ├── mysql/                ← MySQL wire-protocol honeypot package
│   └── dionaea/              ← multi-protocol honeypot package
├── addons/
│   ├── metadata/             ← log sidecar: extracts metadata into inbox
│   └── malware-sender/       ← submits captured samples to malware-catalog
├── server-config/            ← shared host hardening (UFW, SSH, fail2ban)
├── log-stack/                ← Grafana + Loki stack
├── malware-catalog/          ← sample catalog: API, enrichment workers, web UI
│   └── deploy/
│       ├── catalog/          ← FastAPI backend + SQLite
│       ├── static-analyzer/  ← YARA, IOC extraction, ssdeep (always on)
│       ├── intel-fetcher/    ← MalwareBazaar + VirusTotal (opt-in)
│       ├── sandbox-submitter/← tria.ge dynamic analysis (opt-in)
│       ├── ui/               ← nginx + hash-routed browser UI
│       └── vector/           ← ships submission events to Loki
├── docs/                     ← design & planning (!DESIGN, !VISION, plan files)
├── terraform/                ← infrastructure-as-code
├── lib/                      ← shared Python library (config, ssh, color, package…)
├── scripts/
│   ├── provision.py          ← end-to-end provisioning (terraform + server setup)
│   ├── redeploy.py           ← update a live server (Tailscale, port 65022)
│   ├── connect.py            ← SSH into a server
│   ├── sync_ips.py           ← write IPs from Terraform + Tailscale to state.json
│   ├── get_logs.py           ← pull logs from a honeypot
│   ├── gen_ts_key.py         ← generate a Tailscale auth key
│   ├── check_ssh_keys.py     ← check / generate SSH keys for all servers
│   ├── check_logs.py         ← check log stream freshness in Loki
│   ├── check_disk.py         ← check disk usage on all servers (25 GB Nanode limit)
│   ├── test_loki.py          ← push a test log to Loki to verify the stack
│   └── test_honeypot.py      ← run smoke tests for a honeypot type
├── honey-net.json            ← server manifest (single source of truth)
├── state.json                ← gitignored, written by sync_ips.py
├── honey.py                  ← interactive launcher for all commands
├── _lib.py                   ← backward-compat shim for honey-pots/*/test.py
├── setup.ps1                 ← one-time local setup (Windows)
├── setup.sh                  ← one-time local setup (macOS/Linux)
└── requirements.txt
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

**2. SSH key pairs** — one for each server. Set the path in `honey-net.json` (`ssh_key` field):
```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\log-stack-linode"
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\mysql-ssh-honeypot"
```

**3. Linode API token** — cloud.linode.com → Profile → API Tokens → Create (Read/Write Linodes scope).

**4. Tailscale account** — [tailscale.com](https://tailscale.com). Free tier covers this entire project.
- Tailscale API key (tailscale.com → Settings → Keys → Generate API key)
- Saved to `~/.tailscale-apikey` on first run; subsequent runs read it automatically
- Generate auth keys with `python scripts/gen_ts_key.py` (non-ephemeral for backends, `--ephemeral` for honeypots)

## Provisioning

Terraform reads `honey-net.json` directly. Root passwords are auto-generated and stored in Terraform state.

```powershell
cd terraform
copy terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — add linode_token (and optionally region)
terraform init
terraform plan
terraform apply
cd ..
python scripts/sync_ips.py    # reads terraform output + Tailscale API, writes state.json
```

To destroy all infrastructure:
```powershell
cd terraform && terraform destroy
```

## Deployment order

Deploy log-stack first — its Tailscale IP is required by Vector on every honeypot.

**1. Deploy log-stack**
```
python scripts/provision.py --server log-stack
```
Prompts for Tailscale API key, Grafana admin password, then runs end-to-end: waits for SSH, generates Tailscale auth key, SCPs files, runs `setup.sh`, polls Tailscale until registered, and writes the Tailscale IP to `state.json`.

If interrupted and restarted, servers already in `state.json` are skipped (with a prompt). Use `--force` to reprovision without prompting.

**2. Deploy honeypots**
```
python scripts/provision.py --server mysql-ssh
```
Same flow. `provision.py` reads `LOKI_HOST` from `state.json` (set in step 1) and passes it to `setup.sh` automatically. After setup, port 22 closes and SSH moves to port 65022 (Tailscale only).

**3. Verify logs are flowing**
```
python scripts/test_loki.py    # Push a test log line to Loki
```
Open Grafana at `http://<log-stack-tailscale-ip>:3000`:
- `{job="cowrie"}` — raw Cowrie events
- `{job="mysql"}` — raw MySQL events
- `{job="dionaea"}` — raw Dionaea events
- `{job="auth"}` — host auth.log
- `{job="events"}` — normalised cross-honeypot stream

## Re-deploying after changes

```
python scripts/redeploy.py --server mysql-ssh   # Tailscale required
python scripts/redeploy.py --server log-stack
```

Copies updated files to the server via Tailscale (port 65022) and runs `docker compose up -d`. Does not touch system configuration; `.env` is preserved.

## Pulling logs

```
python scripts/get_logs.py --server mysql-ssh   # saves logs/ to logs/mysql-ssh/
```

By convention each honeypot writes JSON logs to `/opt/<server>/<honeypot>/volumes/logs/<honeypot>.json`. `get_logs.py` reads from these paths automatically.

## Useful server commands

```bash
# On a honeypot server (e.g., mysql-ssh)
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

### Optional — malware-catalog enrichment

The catalog runs three enrichment workers alongside the API. The first (`static-analyzer`: YARA, IOC extraction, ssdeep, PE/ELF parsing) needs no setup. The other two only run if you provide a key:

**VirusTotal API key** *(optional, enables AV verdict enrichment)* — [virustotal.com/gui/my-apikey](https://www.virustotal.com/gui/my-apikey). Free tier (4 req/min) is enough. Lookup-only; the catalog never uploads samples to VT.

**Triage API key** *(optional, enables dynamic sandbox analysis)* — [tria.ge/account/api](https://tria.ge/account/api). Free public tier available. Submissions are **public**, so by default only ELF/PE samples (already public via MalwareBazaar) are uploaded.

Both keys go in `malware-catalog/deploy/.env` on the catalog server (see `.env.example`). Without them, `intel-fetcher` runs MalwareBazaar lookups only and `sandbox-submitter` stays off. Apply with `python redeploy.py --server malware-catalog`.

## honey.py — interactive launcher

`python honey.py` opens a numbered menu for all commands. Select a command; for options that vary (e.g. ephemeral vs. persistent Tailscale key, pre-setup vs. normal SSH), it prompts before running.

```
Honey-Net

  1   provision    End-to-end provisioning: terraform + server setup
  2   redeploy     Update a live server (port 65022, Tailscale)
  3   connect      Open an SSH session to a server
  4   sync         Sync IPs from Terraform + Tailscale to state.json
  5   logs         Pull logs from a honeypot server
  6   gen-key      Generate a Tailscale auth key
  7   check-keys   Check SSH keys in honey-net.json; generate missing
  8   check-logs   Check log stream freshness in Loki
  9   check-disk   Check disk usage on all servers (25 GB Nanode limit)
  10  test-loki    Push a test log to Loki to verify the stack
  11  test         Run smoke tests for a honeypot from this machine
  q   quit

Select:
```

Commands that need a server name prompt for one when omitted. All commands also accept direct flags:

```
python honey.py provision --server mysql-ssh
python honey.py connect --server mysql-ssh
python honey.py connect --server log-stack --pre-setup
python honey.py redeploy --server mysql-ssh
python honey.py logs --server mysql-ssh
python honey.py sync
python honey.py gen-key --ephemeral
python honey.py check-keys
python honey.py check-logs
python honey.py check-disk
python honey.py check-disk --server log-stack
```

Or invoke the scripts directly — same flags, same behavior:

```
python scripts/connect.py --server mysql-ssh
python scripts/redeploy.py --server mysql-ssh
python scripts/get_logs.py --server mysql-ssh
python scripts/sync_ips.py
```

## Adding a honeypot server

1. Add an entry to `honey-net.json` with `name`, `type`, `ssh_key`, `ports`, and `honeypots`.
2. Generate an SSH key pair for the new server.
3. If it's a new honeypot type, create `honey-pots/<name>/` with the standard package layout.
4. Run `python honey.py provision --server <name>` — creates the VM via Terraform and runs full setup.

No changes to `terraform/main.tf` or any root script are needed. See `honey-pots/CLAUDE.md` for honeypot package structure.
