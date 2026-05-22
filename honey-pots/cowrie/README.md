# cowrie

SSH and Telnet honeypot package for [honey-net](../../README.md). Runs the [Cowrie](https://github.com/cowrie/cowrie) honeypot plus a YARA-based malware analyzer sidecar. Deployed as part of a honeypot server via the honey-net control plane.

## What it captures

| Data | How |
|------|-----|
| SSH/Telnet sessions | Full PTY interaction logged to `cowrie.json` |
| Commands run by attackers | Per-session command log |
| Malware download attempts | URLs and raw binaries saved to `downloads/` |
| Credential attempts | Username + password pairs for every login |
| Attacker SSH public keys | Planted keys captured in `authorized_keys` |
| YARA rule hits | Analyzer sidecar scans downloads and emits results |

Logs are shipped to Loki by Vector with labels `{job="cowrie"}` and `{job="malware"}`.

## Ports

| Port | Protocol | Notes |
|------|----------|-------|
| 22 | SSH | Cowrie |
| 23 | Telnet | Cowrie |
| 65022 | SSH | Real admin access, Tailscale only |

## Layout

```
deploy/
  docker-compose.yml       # cowrie, analyzer, and vector services
  .env.example
  cowrie/
    etc/
      cowrie.cfg           # main Cowrie config
      userdb.txt           # accepted credentials (root:x:* = any password)
      authorized_keys      # planted SSH keys — stage-2 sessions land here
    honeyfs/               # fake filesystem presented to attackers
    txtcmds/               # fake command output (uname, uptime, free, lscpu)
  analyzer/
    Dockerfile             # Python + YARA
    analyze.sh
    rules/                 # YARA rule files (backdoors, downloaders, miners, mirai)
  vector/
    vector.toml            # ships cowrie.json + host logs to Loki
  setup/
    fragment.sh            # host provisioning steps (appended to server-config/setup.sh)

CLAUDE.md                  # protocol details, log paths, known gotchas
test.py                    # smoke test — verifies SSH port is reachable
```

## Configuration

**`cowrie/etc/cowrie.cfg`** — main config. Key settings:
- `auth_class = UserDB` with `userdb.txt` entry `root:x:*` accepts any password for root.
- `state_path = var/lib/cowrie` is required — omitting it breaks auth silently.
- Fake hostname, version banner, and filesystem path are all set here.

**`cowrie/etc/userdb.txt`** — accepted credential list. Format: `username:uid:password` where `*` matches any password.

**`cowrie/etc/authorized_keys`** — SSH public keys that Cowrie will accept for key-based auth. Attackers often plant a key then reconnect — add observed keys here to capture stage-2 sessions.

**`cowrie/honeyfs/`** — fake filesystem files served to attackers (passwd, hostname, motd, etc.).

**`cowrie/txtcmds/`** — static output for commands like `uname -a`, `uptime`, `free -m`. Attackers run these to fingerprint the host.

## YARA analyzer

The `analyzer` sidecar watches the downloads directory and scans new files against the rules in `analyzer/rules/`. Hits are written to `malware-analysis.json` and shipped to Loki under `{job="malware"}`.

Current rule sets: backdoors, downloaders, cryptominers, Mirai variants.

## Deploying

This package is deployed by the honey-net control plane — not standalone. From the honey-net root:

```
python deploy.py --server <server-name>
python connect.py --server <server-name> --pre-setup
```
```bash
sudo bash /root/<server-name>/setup.sh
```

To push updates to a live server:
```
python redeploy.py --server <server-name>
```

## Testing

From the honey-net root (server must be running):
```
python honey-pots/cowrie/test.py
```
Verifies the SSH port is reachable and returns a banner.
