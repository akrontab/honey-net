# Adding a Honeypot Package

A honeypot package is a self-contained folder under `honey-pots/` that teaches `provision.py` and `redeploy.py` how to deploy a service. Adding one requires no changes to Terraform or `server-config/`.

To create a new package, copy an existing one (`cowrie/` is simplest, `mysql/` for a built-locally Python service) and adapt. The rest of this file documents the contracts those examples follow.

## Filesystem conventions

| Concern | Convention |
|---|---|
| JSON log on host | `./volumes/logs/<honeypot>.json` (filename = package name) |
| JSON log in vector container | `/logs/<honeypot>/<honeypot>.json` (assembler re-roots) |
| Sample drop on host | `/opt/<server>/inbox/<honeypot>/` |
| Sample drop in honeypot container | `/samples/` (per-honeypot mount) |
| Shared inbox parent | `/opt/<server>/inbox/` — created by `server-config/setup.sh` `chmod 777` |
| Per-honeypot inbox subdir | created by the honeypot's `fragment.sh` |

Honeypots write samples with whatever filename their upstream code picks (sha256 for cowrie). The `metadata` addon canonicalises to `/inbox/<sha256>` + `/inbox/<sha256>.meta.json`. Honeypots that don't capture samples skip the `/samples` mount and the `mkdir inbox/<name>` step.

## docker-compose.yml conventions

Each honeypot's compose file is included into a generated top-level compose by `provision.py` — it must not declare networks or volumes that conflict with siblings.

- All services on a `honeypot` network (driver: bridge), declared in each compose for idempotency.
- Always `restart: unless-stopped` and `security_opt: [no-new-privileges:true]`.
- Set `deploy.resources.limits` — Nanode has 1GB RAM total.
- Include a `vector` service that ships `./volumes/logs/` + host `/var/log` to Loki.

## vector/vector.toml — normalized event schema

Each honeypot's Vector includes a `remap` transform that emits a parallel `{job="events", honeypot=<name>}` stream alongside the raw `{job="<honeypot>"}` stream. The schema is a **contract**: a new honeypot that fills the core + the standard `meta` keys for its capabilities appears in every cross-cutting dashboard, alert, and the campaign tooling with **zero dashboard edits**. The design is a lean flat **core** (universal, stable) plus a governed nested **`meta`** object each pot owns. See `docs/normalized-schema-plan.md` for the rationale.

### Core (the universal contract)

```json
{
  "timestamp":     "ISO-8601 UTC",
  "honeypot":      "<package name>",
  "protocol":      "ssh|telnet|mysql|smb|ftp|http|...",
  "src_ip":        "1.2.3.4",
  "src_port":      54321,
  "session_id":    "...",
  "event_type":    "connect|login|command|query|download|session_end",
  "username":      "root",
  "password":      "...",
  "payload":       "...",
  "sample_sha256": "...",
  "meta":          { /* governed vocabulary — see below */ }
}
```

All fields except `timestamp`, `honeypot`, `src_ip`, and `event_type` may be `null`. Core fields are **stable** — existing queries and dashboards on them keep working; do not repurpose a core field's meaning. Events whose source `eventid`/`type` doesn't map to a known `event_type` are dropped via `abort`.

- `payload` is the **command/query input** (`command`/`query` events). On `download` events the fetch URL lives in `meta.url`, **not** `payload` — `payload` is `null` on downloads.

The Loki job label (`labels.job`) is what LogQL queries filter on — use a short lowercase name matching the package name. Loki flattens `meta` on `_`, so it reads naturally: `{job="events"} | json | meta_login_success="true"`. Every honeypot also ships `auth.log` and `syslog` from `/hostlogs` to `{job="auth"}` / `{job="syslog"}`.

### `meta` — governed vocabulary, not a free bag

`meta` carries richness the lean core leaves out. It has **two tiers**, and the distinction is load-bearing:

- **Standard capability keys** — the concept-named vocabulary in the table below. A pot with that capability **must** emit the standard key, spelled exactly, so cross-cutting panels match every pot at once. The names are the cross-protocol *concept* (`client_fingerprint`), never a protocol mechanism (`hassh`); each pot maps its mechanism into the concept.
- **Pot-private keys** — genuinely unique fields only that pot's own (per-protocol) dashboards read, e.g. Cowrie `arch` or a ttylog reference. Namespace freely; they are not part of the contract.

The contract lives as **N copy-pasted `remap` transforms** (one per pot, no shared VRL include today), so the single thing preventing silent key drift is this table. Spell standard keys from it verbatim. (A lint/test that asserts each pot emits its declared standard keys is deferred until a third pot's `meta` lands — see plan Q1.)

#### Standard `meta` keys (by capability)

| `event_type` | `meta` key | Concept | Cowrie | MySQL | HTTP |
|---|---|---|---|---|---|
| `login` | `login_success` | auth outcome (`true`/`false`) | `success`/`failed` eventid | always-accept → `true` | form / basic result |
| `login` | `auth_method` | how they authed | `password` / `pubkey` | `native_password` | `basic` / `form` |
| `connect` | `client_fingerprint` | client identity (value) | HASSH | — | JA3 / JA4 |
| `connect` | `fingerprint_type` | which algorithm produced it | `hassh` | — | `ja3` / `ja4` |
| `connect` | `client_version` | client banner | `cowrie.client.version` | — | User-Agent |
| `download` | `url` | fetch URL (also the `payload` slot's old home) | `raw.url` | — | upload origin |
| `download` | `dl_host` | staging infra (host of `url`) | derived | — | — |
| `download` | `dl_filename` | payload name | derived | — | upload name |
| `command` | `command_success` | did it run (`true`/`false`) | `input` / `failed` eventid | — | — |
| `query` | `database` | target DB | — | `raw.database` | — |

`client_fingerprint` is **one field plus a `fingerprint_type` discriminator** (not separate `hassh`/`ja3` keys) so a cross-pot fingerprint query matches one key and a new algorithm slots in without a schema change.

### The hard rule (keeps it from re-coupling)

**Cross-cutting dashboards and alerts query `{job="events"}` only.** Anything reaching into `{job="<pot>"} | eventid=...` belongs in a **per-protocol** dashboard (`cowrie-overview`, `mysql-overview`). Per-protocol dashboards staying on the raw stream is correct — that is their job. A panel titled "across all honeypots" that unions raw per-pot paths is the anti-pattern this contract exists to remove.

Per-honeypot `CLAUDE.md` documents that pot's own `meta` mapping (which standard keys it emits and how it derives each).

## setup/fragment.sh

`provision.py` concatenates `server-config/setup.sh` with each honeypot's `fragment.sh` in the order listed under `"honeypots"` in `honey-net.json`. The result is the `setup.sh` that lands on the server.

Environment variables available:

| Variable | Value |
|---|---|
| `$DEPLOY_DIR` | `/opt/<server-name>` — where files are rsynced |
| `$SERVER_NAME` | Server name from honey-net.json |
| `$TAILSCALE_IP` | Server's Tailscale IP (set after Tailscale joins) |
| `$REAL_SSH_PORT` | `65022` |
| `$LOKI_HOST` | log-stack Tailscale IP (read from state.json by setup.sh) |

Fragment responsibilities:
- **Open UFW ports** for the public-facing service.
- **Create volume directories** (Docker assigns wrong ownership if you let it create them lazily). **Always `chown honey:honey` the directory immediately after `mkdir -p`** — `setup.sh` runs `chown -R honey:honey $DEPLOY_DIR` before fragments execute, so any directory a fragment creates afterward is root-owned. A root-owned log dir silently prevents the container from writing (the container's uid=0 maps to `honey` on the host via the rootless user namespace, appearing as `others` against a root-owned dir). Symptom: container logs fine to stdout, log file never appears, Loki stream stays empty.
- **Create the per-honeypot inbox subdir** with `chmod 777` if it captures samples.
- **Fix ownership** for non-root container UIDs (Cowrie is 999).
- **Build locally-built images explicitly in sequence.** Never `docker compose up --build` — concurrent BuildKit crashes dockerd (see `mysql/CLAUDE.md`).
- **Run `docker compose up -d` only if this fragment is designed to always be last.** Cowrie's fragment does not — it is always followed by addons on real servers. MySQL's fragment always runs `up -d` (designed as a standalone-terminal honeypot). Malware-sender always runs `up -d` as the terminal addon. On multi-component servers, a non-terminal fragment that runs `up -d` will start the stack before later images are built, then the final fragment starts it again.

## honey-net.json entry

```json
{
  "name": "my-server",
  "type": "honeypot",
  "ssh_key": "~/.ssh/my-server-linode",
  "honeypots": ["cowrie", "my-honeypot"],
  "ports": [22, 23, 9999],
  "tailscale_ephemeral": true
}
```

`tailscale_ephemeral: true` auto-removes the Tailscale node when the VM is destroyed — use for all honeypot servers.

## Checklist for a new honeypot

- [ ] `deploy/docker-compose.yml` (+ `../inbox/<name>:/samples` mount if it captures binaries)
- [ ] `deploy/vector/vector.toml` (sources + normalising transform + sinks) — emit the standard `meta` keys for each capability the pot has (see the `meta` table above)
- [ ] `deploy/.env.example`
- [ ] `deploy/setup/fragment.sh`
- [ ] `CLAUDE.md` (protocol, log paths, event mapping, gotchas)
- [ ] `test.py` (smoke test — see existing honeypots for the `_lib` import pattern)
- [ ] Entry in `honey-net.json`
- [ ] SSH key pair at the `ssh_key` path
- [ ] `python scripts/provision.py --server <name>`
- [ ] Grafana dashboard under `log-stack/deploy/grafana/provisioning/dashboards/`

## Wrapping an upstream honeypot (code we don't control)

When the upstream pot is a third-party project (PyPI package, prebuilt image, git
source) follow the general process in `docs/wrapping-upstream-honeypots-plan.md`.
The short version:

**The package machinery requires no changes.** `provision.py` / `redeploy.py` only
build services that declare a `build:` block — an `image:`-only service just pulls
and runs. The vector assembler merges regardless of image source.

**The work lives in two files this package already owns:**

1. **Image sourcing** — choose one mode:
   - **Mode A**: `image: ghcr.io/vendor/foo@sha256:<digest>` — pin by digest, never a moving tag
   - **Mode B**: thin `Dockerfile` with `pip install foo==<version>` (or equivalent) — used
     when upstream has no maintained image. Slots into the existing build-in-sequence path.

2. **Vector adapter** — the upstream emits its own format; the `remap` translates it.
   Pick the source by what upstream writes:

   | Upstream emits | Vector source | Adapter |
   |---|---|---|
   | JSON file (alien field names) | `file` | `parse_json!` + re-key |
   | CSV file | `file` | `parse_csv!` + positional mapping |
   | plain text / key-value | `file` | `parse_regex!` / `parse_grok!` first |
   | stdout only | `docker_logs` | parse line + remap |
   | sqlite / binary DB | — | sidecar writes JSONL → `file` |

   Fill the standard `meta` keys for each capability the pot has (the table above)
   so it lands in every cross-cutting dashboard with zero dashboard edits.

**Checklist additions for a wrapped pot:**
- [ ] Choose Mode A or Mode B — document in CLAUDE.md
- [ ] `deploy/<svc>/Dockerfile` **only if Mode B**
- [ ] Upstream config file if needed, mounted read-only, log paths → your volume
- [ ] Capture-writer sidecar **only if** upstream captures binaries

**Reference implementation:** `honey-pots/heralding/` — Mode B wrap of
`heralding==1.0.7` (PyPI), CSV log adapter.
