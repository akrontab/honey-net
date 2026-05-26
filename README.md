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
Select **logs** to pull log files locally. Open Grafana at `http://<log-stack-tailscale-ip>:3000` — logs appear under `{job="cowrie"}`, `{job="mysql"}`.

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
**2. Linode API token** — cloud.linode.com → Profile → API Tokens → Create (Read/Write Linodes scope).

**3. Tailscale API key** — tailscale.com → Settings → Keys → Generate API key. Saved to `~/.tailscale-apikey` on first use; subsequent runs read it from there automatically.

### Optional — malware-catalog enrichment

The catalog runs three enrichment workers alongside the API. The first (`static-analyzer`: YARA, IOC extraction, ssdeep, PE/ELF parsing) needs no setup. The other two only run if you provide a key:

**4. VirusTotal API key** *(optional, enables AV verdict enrichment)* — [virustotal.com/gui/my-apikey](https://www.virustotal.com/gui/my-apikey). Free tier (4 req/min) is enough. Lookup-only; the catalog never uploads samples to VT.

**5. Triage API key** *(optional, enables dynamic sandbox analysis)* — [tria.ge/account/api](https://tria.ge/account/api). Free public tier available. Submissions are **public**, so by default only ELF/PE samples (already public via MalwareBazaar) are uploaded.

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

1. Add an entry to `honey-net.json` with `name`, `ssh_key`, `honeypots`, `ports`.
2. Generate an SSH key pair for it.
3. Run `python honey.py provision --server <name>` — creates the VM and runs full setup.

No changes to `terraform/main.tf` or any root script are needed.

## Currently deployed honeypots

| Package | Protocols | Ports | Captures |
|---------|-----------|-------|---------|
| cowrie | SSH, Telnet | 22, 23 | Sessions, commands, malware downloads, attacker SSH keys |
| mysql | MySQL | 3306 | Credentials (username), SQL queries, database enumeration |
