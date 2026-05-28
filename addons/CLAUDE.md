# Addons

Optional processing components that run alongside honeypots on honeypot servers. They process or route data the honeypots produce; they never face the internet. Package structure mirrors honey-pot packages (see `honey-pots/CLAUDE.md`).

Each server's `honey-net.json` entry lists which addons it runs:

```json
{
  "name": "mysql-ssh",
  "type": "honeypot",
  "honeypots": ["cowrie", "mysql"],
  "addons":    ["metadata", "malware-sender"]
}
```

`provision.py` and `redeploy.py` treat addons identically to honeypots for package assembly.

## Available addons

| Addon | Purpose |
|---|---|
| `metadata` | Walks `/inbox/<honeypot>/`, canonicalises (sha256-rename), enriches sidecars |
| `malware-sender` | Polls inbox for canonicalised sidecars; submits samples + provenance to the catalog |

## Shared inbox

`/opt/<server>/inbox/` exists on **every honeypot server** regardless of which addons run — created by `server-config/setup.sh` (not by any addon) with `chmod 777` so containers running as different UIDs all read/write.

```
/opt/<server>/inbox/
  cowrie/                            # per-honeypot drop dir, created by cowrie's fragment
    <whatever>                       # cowrie's binary (sha256-named by cowrie convention)
    <whatever>.capture.json          # provenance sidecar from cowrie's capture-writer
  dionaea/                           # per-honeypot drop dir, created by dionaea's fragment
    <md5>                            # dionaea's binary (md5-named)
  <sha256>                           # canonical binary (written by metadata)
  <sha256>.meta.json                 # enriched sidecar (written by metadata)
```

| Path | Written by | Consumed by |
|---|---|---|
| `<honeypot>/<name>` | honeypot container (via `/samples` mount) | metadata (canonicalises) |
| `<honeypot>/<name>.capture.json` | honeypot-specific capture writer | metadata (merges into sidecar) |
| `<sha256>` | metadata | malware-sender |
| `<sha256>.meta.json` | metadata | malware-sender |

Per-honeypot subdirs are created by each honeypot's `fragment.sh`. The metadata addon doesn't know which honeypots exist; it walks whatever subdirs are present.

## Fragment order

Fragments append to `setup.sh` as: **honeypots first, then addons**. The **last addon's fragment** runs `docker compose up -d`. For `mysql-ssh` the order is: cowrie → mysql → metadata → malware-sender (starts stack).

## Adding a new addon

- [ ] `deploy/docker-compose.yml`, `.env.example`, `setup/fragment.sh`
- [ ] `CLAUDE.md`
- [ ] Add `"<name>"` to the `addons` list of any server that should run it

No root script changes are needed. `redeploy.py` discovers locally-built images by scanning `docker-compose.yml` for `build:` keys.
