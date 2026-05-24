# Addons

Addons are optional processing components that run alongside honeypots on honeypot
servers. They are distinct from honeypots (which face the internet and capture traffic)
and from backend services (log-stack, malware-catalog) which run on their own servers.

## What addons do

- Process or route data that honeypots produce
- Never face the internet
- Can be included or excluded per server via `honey-net.json`

## How addons are deployed

Addons are listed under `"addons"` in a server's `honey-net.json` entry:

```json
{
  "name": "mysql-ssh",
  "type": "honeypot",
  "honeypots": ["cowrie", "mysql"],
  "addons":    ["metadata", "malware-sender"]
}
```

`provision.py` and `redeploy.py` treat addons identically to honeypots for package
assembly — they copy `addons/<name>/deploy/` into the deploy package and append
`setup/fragment.sh` to the server's `setup.sh`.

## Layout

Each addon follows the same structure as a honeypot package:

```
addons/<name>/
  deploy/
    <name>/            # Application source + Dockerfile
    docker-compose.yml
    .env.example
    setup/
      fragment.sh
  CLAUDE.md
```

## Available addons

| Addon | Purpose |
|-------|---------|
| `metadata` | Watches the inbox for new binary samples; writes `{sha256}.meta.json` sidecars |
| `malware-sender` | Polls inbox for complete sidecars; submits samples to the malware catalog |

## Shared inbox

The two addons (and Cowrie) share a bind-mounted directory at `/opt/<server>/inbox/`
on the host, mounted as `/inbox` inside each container.

| File | Written by | Read by |
|------|-----------|---------|
| `{sha256}` | cowrie (via assembled inbox mount) | malware-sender |
| `{sha256}.meta.json` | metadata | malware-sender |

The inbox is created by `metadata`'s `fragment.sh` with permissions `777` so both
Cowrie (UID 999) and root containers can write to it.

## Fragment order

Fragments are appended to `setup.sh` in the order: honeypots first, then addons.
The last addon's fragment is responsible for starting the stack (`docker compose up -d`).
For `mysql-ssh` the order is: cowrie → mysql → metadata → malware-sender (starts stack).

## Adding a new addon

No root script changes are needed. The control plane reads everything it needs from the
package at runtime — `redeploy.py` discovers locally-built images by scanning the
addon's `docker-compose.yml` for `build:` keys.

- [ ] Create `addons/<name>/deploy/docker-compose.yml`
- [ ] Create `addons/<name>/deploy/.env.example`
- [ ] Create `addons/<name>/deploy/setup/fragment.sh`
- [ ] Create `addons/<name>/CLAUDE.md`
- [ ] Add `"<name>"` to the `addons` list of any server that should run it
