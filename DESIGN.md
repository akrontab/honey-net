Honey-net Design
==========================

## Overview

Honey-net is a cloud-based honeypot network with pluggable honeypot services and a separate admin network for log aggregation and analysis.

The project is built around these design pillars:

**1. Cheaper Than Starbucks™** — Running the full infrastructure should cost less than a coffee run. All hosts are minimal cloud VMs (currently Linode Nanodes at $5/mo each), and services are chosen for low resource overhead.

**2. Swappable components** — No component should be load-bearing in a way that locks the rest of the system in. Grafana and Loki handle dashboards and log storage today; swapping them out should only require changes to the log shipper configuration, not the honeypots or the network design. Vector is the abstraction layer between honeypots and the log backend — honeypots write to files, Vector ships them, and only the sink config changes when the backend does.

**3. Isolation** — Honeypots are explicitly untrusted environments. Docker isolates each honeypot process from the host OS. Admin services (Grafana, Loki) are bound to a private Tailscale IP and never exposed to the public internet. Each honeypot runs on its own VM so a compromise stays contained. Host hardening (UFW, SSH key-only auth, fail2ban) is applied uniformly at deploy time.

**4. Self-describing packages** — Adding a new honeypot or addon must not require changes to any root script. Every behavior the control plane needs (log paths, build requirements, provisioning steps) is declared inside the package itself. Root scripts discover these properties at runtime by reading from the package directory.

Infrastructure-as-Code (currently Terraform) manages all cloud resources so the network can be torn down and rebuilt repeatably.

## Technical Details

Docker is heavily leveraged to host honeypot services because of it's clean separation of applications and server infrastructure. It also adds a layer of defense if the honeypot is jailbroken.

Multiple honey pot services can be run on a single server, and each server has a hardened configuration that is applied at deploy time

Each section describes a major component or a class of components that make up Honey-net. Not all sections represent a deployable component.

### Honey-Net

The honey-net root is the control plane for the entire network. All deployment, connection, and IP management operations run from here. Individual honeypot folders are service packages — they contain Docker config and documentation but have no knowledge of servers or IPs.

Everything lives in a single git repo. Honeypot packages, addons, log-stack, and Terraform are all subdirectories of honey-net — no submodules, no separate repos.

```
honey-net/
  ├── honey-pots/
  │   ├── cowrie/
  │   │   ├── deploy/
  │   │   │   └── docker-compose.yml
  │   │   ├── CLAUDE.md
  │   │   └── test.ps1
  │   └── mysql/
  │       ├── deploy/
  │       │   └── docker-compose.yml
  │       ├── CLAUDE.md
  │       └── test.ps1
  ├── log-stack/
  │   ├── deploy/
  │   │   └── docker-compose.yml
  │   └── CLAUDE.md
  ├── server-config/
  │   └── CLAUDE.md
  ├── terraform/
  │   └── CLAUDE.md
  ├── CLAUDE.md
  ├── DESIGN.md
  ├── honey-net.json       ← authored network manifest
  ├── state.json           ← gitignored, written by sync-ips.ps1
  ├── deploy.ps1           ← first deploy (port 22, runs setup.sh)
  ├── redeploy.ps1         ← update a live server (port 65022, restarts stack)
  ├── connect.ps1          ← SSH into a server
  ├── sync-ips.ps1         ← write terraform IPs and Tailscale IPs to state.json
  └── get-logs.ps1         ← pull logs from a server
```

#### honey-net.json

`honey-net.json` is the authored manifest for the network. It is the single source of truth for every server — backend services and honeypots alike. All root scripts read from this file, so there is one place to look up any server in the network.

Each top-level object represents a server. The `type` field determines how deployment is handled:

- **`backend`** — stable VPN-only services (Grafana, Loki, malware analysis). Deployed directly from `<name>/deploy/`. Tailscale key is non-ephemeral so the node persists across reboots. Changes infrequently.
- **`honeypot`** — public-facing decoy servers. Deployed by composing one or more service packages from `honey-pots/<name>/deploy/`. Tailscale key is ephemeral so the node auto-removes when the VM is destroyed. Added and removed ad-hoc.

```json
[
  {
    "name": "log-stack",
    "type": "backend",
    "terraform_module": "log_stack",
    "terraform_output": "log_stack_ip",
    "ssh_key": "~/.ssh/log-stack-linode",
    "tailscale_ephemeral": false,
    "ports": [],
    "honeypots": []
  },
  {
    "name": "cowrie-honeypot",
    "type": "honeypot",
    "terraform_module": "cowrie",
    "terraform_output": "cowrie_ip",
    "ssh_key": "~/.ssh/cowrie-linode",
    "tailscale_ephemeral": true,
    "ports": [22, 23],
    "honeypots": ["cowrie"]
  },
  {
    "name": "mysql-honeypot",
    "type": "honeypot",
    "terraform_module": "mysql_honeypot",
    "terraform_output": "mysql_ip",
    "ssh_key": "~/.ssh/mysql-linode",
    "tailscale_ephemeral": true,
    "ports": [3306],
    "honeypots": ["mysql"]
  }
]
```

| Field | Description |
|-------|-------------|
| `name` | Server name — used as the key in `state.json` and in script menus |
| `type` | `backend` or `honeypot` — determines deploy source and Tailscale key behavior |
| `terraform_module` | Matches the module name in `terraform/main.tf` |
| `terraform_output` | Matches the output name in `terraform/outputs.tf` |
| `ssh_key` | Path to the SSH private key for this server |
| `tailscale_ephemeral` | `false` for backends (persist in tailnet), `true` for honeypots (auto-remove on destroy) |
| `ports` | Public-facing ports this server exposes — used by help dialogs, validation scripts, and network auditing. Informational only (see gotcha below). |
| `honeypots` | Honeypot package names to compose onto this server — `honeypot` type only, resolved to `honey-pots/<name>/deploy/` |

A honeypot server listing multiple packages (e.g. `"honeypots": ["cowrie", "mysql"]`) gets both composed and deployed together. Backend servers leave `honeypots` and `ports` as empty arrays.

> **Gotcha — `ports` is metadata, not enforcement.** UFW rules are opened by each honeypot's `setup/fragment.sh`, not by reading this field. `ports` is a declaration for tooling — if a fragment opens a port that isn't listed here, or this field is updated without updating the fragment, the server's actual firewall state wins. Keep them in sync manually when adding or changing honeypots.

#### state.json

`state.json` is the runtime counterpart to `honey-net.json`. It is gitignored and written by `sync-ips.ps1` after `terraform apply`. All root scripts read server IPs from here.

```json
{
  "log-stack":       "1.2.3.4",
  "cowrie-honeypot": "5.6.7.8",
  "mysql-honeypot":  "9.10.11.12"
}
```

#### Root scripts

All deployment and connection operations run from the honey-net root. Each script reads `honey-net.json` for server definitions and `state.json` for IPs.

**`deploy.ps1 [-Server <name>] [-h]`**
First deploy only — server must be fresh with SSH on port 22. Assembles the deployment package (generates the `include:`-based `docker-compose.yml`, concatenates `server-config/setup.sh` with each honeypot's `setup/fragment.sh`), SCPs the package to the server, and runs setup.sh. After setup.sh completes, SSH moves to port 65022. Use `redeploy.ps1` for all subsequent updates.

**`redeploy.ps1 [-Server <name>] [-h]`**
Updates a live server — SSH on port 65022 via the server's Tailscale IP, host hardening already in place. SCPs updated files and runs `docker compose up --build`. Does not touch system configuration. If `-Server` is omitted, an interactive menu is shown. Requires Tailscale running locally.

**`connect.ps1 [-Server <name>] [-h]`**
Opens an SSH session to the target server on port 65022 via the server's Tailscale IP from `state.json`. If `-Server` is omitted, an interactive menu is shown. Requires Tailscale running locally.

**`sync-ips.ps1`**
Reads `terraform output -json` and writes public IPs to `state.json`. Also SSHes to each backend server to capture its Tailscale IP (`tailscale ip -4`), storing both IPs per server:
```json
{
  "log-stack": { "public_ip": "1.2.3.4", "tailscale_ip": "100.x.x.x" },
  "cowrie-honeypot": { "public_ip": "5.6.7.8", "tailscale_ip": null }
}
```
Honeypot deploys read `tailscale_ip` from the log-stack entry to configure Vector's Loki endpoint.

**`get-logs.ps1 [-Server <name>] [-h]`**
Pulls log files from the target server to a local `logs/` directory.

All scripts print a help dialog when passed `-h` or `--help`. The `SERVERS` block in each help dialog is generated live from `honey-net.json` — server names, types, ports, and honeypots — so it never goes stale. Interactive menus show each server's name, type, exposed ports, and current IP (or `(no IP — run sync-ips.ps1)` if `state.json` has no entry yet).

#### Deployment decisions summary

| Decision | Choice |
|----------|--------|
| Multi-honeypot compose strategy | Docker Compose `include:` directive, generated by deploy.ps1 |
| setup.sh structure | `server-config/` owns base hardening; each honeypot contributes a `setup/fragment.sh` |
| UFW port management | Fragments open honeypot ports; `ports` in `honey-net.json` is metadata for tooling |
| Loki Tailscale IP | Stored in `state.json` by `sync-ips.ps1` after log-stack setup |
| First deploy vs. re-deploy | Two separate scripts: `deploy.ps1` (public IP, port 22) and `redeploy.ps1` (Tailscale IP, port 65022) |
| Real SSH access | Port 65022 restricted to Tailscale interface only post-setup; fail2ban kept as defense-in-depth |

### log-stack

The log-stack is the admin network's central service host. It runs Grafana and Loki on a single VM that is reachable only over the Tailscale VPN — neither service is exposed to the public internet.

- **Loki** stores log streams from all honeypots. Each honeypot's Vector sidecar pushes to Loki over Tailscale using labeled streams (e.g. `{job="cowrie"}`, `{job="mysql"}`). Retention is currently 30 days, constrained by the Nanode's 25GB disk.
- **Grafana** provides dashboards and ad-hoc log exploration via LogQL. It is provisioned automatically with Loki as the default datasource and a set of pre-built dashboards for each honeypot type.

The log-stack must be deployed before any honeypots. Its Tailscale IP is required to configure the Vector sidecar on each honeypot host.

### honey-pots

Honeypot folders are **service packages**, not deployments. They contain Docker service definitions and documentation but have no knowledge of which server they run on — that is determined entirely by `honey-net.json`.

```
honey-pots/<name>/
  deploy/
    docker-compose.yml     # service definition
    <service>/             # honeypot-specific config or source code
    vector/
      vector.toml          # log shipper — reads honeypot logs, pushes to Loki
    setup/
      setup.sh             # host provisioning (10 steps)
  CLAUDE.md                # what this honeypot captures, protocol details, gotchas
  test.ps1                 # protocol-specific connectivity test
```

All honeypots follow the same conventions:
- Real SSH on port **65022**; the honeypot service on its protocol's default port (22 for SSH, 3306 for MySQL, etc.)
- A Vector sidecar ships log files to Loki over Tailscale
- `setup.sh` applies host hardening and joins the Tailscale network using an ephemeral key — the node auto-removes from the tailnet when the VM is destroyed
- Honeypot VMs are disposable; destroying and recreating one has no effect on the log-stack or other honeypots

Adding a new honeypot means: creating a new subfolder under `honey-pots/` with the standard layout, adding an entry to `honey-net.json`, and adding a module block in `terraform/main.tf`. No changes to the log-stack or any root script are required. The control plane discovers everything it needs from the package at runtime:

| Property | How the control plane reads it |
|---|---|
| Build requirements | Scans `docker-compose.yml` for `build:` keys (`redeploy.py`) |
| Log file to pull | Reads `log_file` from `deploy/logs.json` (`get_logs.py`) |
| Provisioning steps | Appends `setup/fragment.sh` in order (`deploy.py`) |
| Metadata log mounts | Reads `host`/`container` from `deploy/logs.json` (`deploy.py`) |

Currently deployed:

| Name | Protocol | Port | Captures |
|------|----------|------|---------|
| cowrie | SSH / Telnet | 22, 23 | Sessions, commands, malware downloads, attacker SSH keys |
| mysql | MySQL | 3306 | Credentials (username + auth), SQL queries |

### server-config

`server-config/` holds host configuration that is common across all servers in the network — honeypots and log-stack alike. It is not a deployable component on its own; its files are consumed by each host's `setup.sh` at provisioning time.

Currently covers:
- **SSH hardening** — key-only auth, `PermitRootLogin prohibit-password`, port 65022
- **Kernel hardening** — sysctl settings applied via `/etc/sysctl.d/`
- **fail2ban** — defense-in-depth protection on port 65022 (4 retries, 1h ban)
- **Tailscale-restricted SSH** — port 65022 is only reachable from the Tailscale VPN; public internet traffic cannot reach it

Centralizing this configuration means a security improvement is made once and picked up by all hosts on the next redeploy, rather than patching each honeypot's setup script separately.

#### Tailscale-restricted SSH

After Tailscale joins the tailnet, `setup.sh` tightens the UFW rule for port 65022 from open-to-all to Tailscale-interface-only:

```bash
ufw delete allow 65022/tcp
ufw allow in on tailscale0 to any port 65022 comment 'real SSH — Tailscale only'
```

This means the real SSH port is invisible to the public internet. fail2ban is kept as a defense-in-depth layer even though port 65022 should never receive internet traffic.

**Setup ordering constraint** — the Tailscale interface (`tailscale0`) must exist before this rule can be applied. `setup.sh` therefore runs UFW in two phases: port 65022 is opened to all traffic early in setup (so the initial connection over the public IP isn't dropped), then tightened to `tailscale0` only after Tailscale successfully joins.

**Operational implication** — after first deploy completes, port 65022 is no longer reachable on the server's public IP. All subsequent connections (`redeploy.ps1`, `connect.ps1`, `get-logs.ps1`) use the server's Tailscale IP from `state.json`. The operator must have Tailscale running locally to manage any server after initial provisioning.

### terraform

Terraform manages all cloud infrastructure. Each host is a Linode Nanode (1 vCPU, 1GB RAM, $5/mo) provisioned through a reusable `modules/host` module. Adding a host to the network is a single module block in `main.tf`.

After `terraform apply`, `sync-ips.ps1` reads the output IPs and writes them to `state.json` at the honey-net root. Root scripts (`deploy.ps1`, `connect.ps1`, `get-logs.ps1`) all read from `state.json` — no IP files are stored in individual host folders.

State is stored locally (`terraform.tfstate`, gitignored). For multi-machine workflows a remote backend (Terraform Cloud, S3) can be dropped into `main.tf` without changing any other files.

Currently managed hosts:

| Label | Role |
|-------|------|
| log-stack | Grafana + Loki |
| cowrie-honeypot | SSH / Telnet honeypot |
| mysql-honeypot | MySQL honeypot |