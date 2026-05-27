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
| `metadata` | Walks `/inbox/<honeypot>/`, canonicalises (sha256-rename), enriches sidecars |
| `malware-sender` | Polls inbox for canonicalised sidecars; submits samples + provenance to the catalog |

## Shared inbox

The shared inbox is at `/opt/<server>/inbox/` on the host. It is **created by
`server-config/setup.sh`** (not by any addon) with `chmod 777` so containers running as
different UIDs can all read and write. The dir exists on every honeypot server, addons
or not.

### Layout inside the inbox

```
/opt/<server>/inbox/
  cowrie/                              # per-honeypot drop dir, created by cowrie's fragment
    <whatever>                         # cowrie's binary (filename = sha256 by cowrie convention)
    <whatever>.capture.json            # provenance sidecar written by cowrie's capture-writer
  dionaea/                             # per-honeypot drop dir, created by dionaea's fragment
    <md5>                              # dionaea's binary (md5-named by dionaea convention)
  <sha256>                             # canonicalised binary (written by metadata)
  <sha256>.meta.json                   # enriched sidecar (written by metadata)
```

| Path | Written by | Read / consumed by |
|------|-----------|--------------------|
| `<honeypot>/<name>` | the honeypot container (via `/samples` mount) | metadata (canonicalises) |
| `<honeypot>/<name>.capture.json` | honeypot-specific capture writer | metadata (merges into sidecar) |
| `<sha256>` | metadata (moved from `<honeypot>/`) | malware-sender |
| `<sha256>.meta.json` | metadata | malware-sender |

Per-honeypot subdirs are created by each honeypot's `fragment.sh` (e.g. cowrie's
fragment does `mkdir -p $DEPLOY_DIR/inbox/cowrie && chmod 777 ...`). The metadata addon
doesn't know which honeypots exist; it just walks whatever subdirs are present.

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
