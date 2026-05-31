# Design

Architectural patterns behind honey-net's package system and data flows. Per-component conventions (file layouts, env vars, checklists) live in the component CLAUDE.md files — this document explains the model they implement.

## Package model

A package is a self-contained directory under `honey-pots/` or `addons/` that declares everything the control plane needs to deploy it:

| File | Role |
|------|------|
| `deploy/docker-compose.yml` | Service definition; merged into the server's combined stack |
| `deploy/setup/fragment.sh` | One-time provisioning steps (ports, dirs, ownership) |
| `deploy/vector/vector.toml` | Log routing; merged into the server's Vector agent config |

`provision.py` and `redeploy.py` discover packages listed in `honey-net.json` and assemble them at runtime. They have no per-package knowledge — a new package slots in without any script changes.

See `honey-pots/CLAUDE.md` and `addons/CLAUDE.md` for the conventions each file must follow.

## Deployment assembly

For each honeypot server, `provision.py` assembles a single deployment package by combining:

1. `server-config/setup.sh` — base host hardening applied uniformly to every host
2. Each honeypot's `fragment.sh`, in the order listed in `honey-net.json`
3. Each addon's `fragment.sh`, in declaration order

The resulting `setup.sh`, merged `docker-compose.yml`, and combined `vector.toml` are rsynced to the server and run once. The ordering — honeypots before addons, last addon starts the stack — ensures addons that consume honeypot output (e.g. `metadata` reading the inbox) only start after the honeypots that write to it are prepared.

## Two-stream logging

Each honeypot ships two parallel log streams to Loki:

- **Raw** (`{job="<honeypot>"}`) — verbatim service events, full fidelity for forensics and session replay.
- **Normalized** (`{job="events", honeypot="<name>"}`) — unified schema produced by a per-honeypot VRL transform in Vector.

The normalized stream exists because raw schemas differ across honeypots — Cowrie uses `eventid`, dionaea uses `type`, the MySQL honeypot uses `event`. Without normalization, cross-honeypot queries require per-source LogQL. The normalized stream makes "all logins across all honeypots" a single expression.

The two streams are complementary: use `{job="events"}` for dashboards and trend analysis; pivot to the raw stream on `session_id` when you need full session detail.

### The VRL transform

The normalizer is a Vector `remap` transform written in VRL (Vector Remap Language), one per honeypot in its `deploy/vector/vector.toml`. It reads the raw JSON source and emits the unified event; the raw stream ships untouched in parallel from the same Vector agent (raw sink `codec = "text"`, events sink `codec = "json"` with `labels.job = "events"`, `labels.honeypot = "<name>"`).

The transform follows the same three-step shape in every pot:

```
raw = parse_json!(string!(.message))            # 1. parse the source line
event_type, _ = get(event_type_map, [raw.eventid])  # 2. map source type → unified type
if event_type == null { abort }                 # 3. drop anything unmapped
. = { "timestamp": raw.timestamp, "honeypot": "cowrie", ... }  # project to the flat schema
```

Three design properties fall out of this shape:

- **Mapping is a per-pot lookup table.** Each pot translates its own type discriminator (Cowrie `eventid`, dionaea `type`, MySQL `event`) into the shared `event_type` vocabulary. Source fields are projected by name; anything the source doesn't carry lands as `null`.
- **The normalized stream is lossy by design.** The `abort` on an unmapped type means events with no `event_type` mapping exist only in the raw stream — noise is filtered out of `{job="events"}`, but so is anything a pot forgot to map. The raw stream is always the complete record.
- **The transform is stateless, per-event.** VRL sees one line at a time with no cross-event memory. A field a honeypot emits only once per session (e.g. Cowrie states `protocol` only on the connect event) is therefore `null` on every later event in that session — recover it by joining on `session_id`, or enrich with a stateful transform.

The contract is convention, not shared code: each pot's `remap` is maintained independently (there is no shared VRL include), so the unified schema is documented in `honey-pots/CLAUDE.md` and re-implemented per pot.

See `honey-pots/CLAUDE.md` for the unified schema and per-honeypot CLAUDE.mds for event mappings.

## Malware pipeline

Captured binaries move through four stages across the honeypot, two addons, and the catalog:

```
1. Honeypot       drops binary to /opt/<server>/inbox/<honeypot>/
                  cowrie also writes <name>.capture.json alongside

2. metadata       computes sha256, renames to /inbox/<sha256>
                  writes /inbox/<sha256>.meta.json merging provenance

3. malware-sender submits binary + sidecar to catalog API, cleans up inbox

4. catalog        dedupes by sha256, runs enrichment workers
```

The two-addon split keeps concerns separate: `metadata` handles hashing and provenance reconstruction without knowing the catalog API; `malware-sender` handles catalog submission without knowing file formats. Neither addon knows which honeypots are running — they operate on whatever appears in the inbox.

`/opt/<server>/inbox/` is created by `server-config/setup.sh` rather than any addon, so samples accumulate even on servers where the addons haven't been deployed yet.

## Rootless Docker and the honey user

Every host runs its Docker stacks under a dedicated `honey` service account using rootless Docker. The key property: `dockerd` runs as `honey`, not as root.

**Why docker group membership is equivalent to root.** In the conventional setup, `dockerd` runs as root and exposes its socket to members of the `docker` group. Any user in that group can instruct the root-owned daemon to mount the host filesystem and launch a privileged container — a one-command full host compromise:

```bash
docker run --rm -v /:/host --privileged ubuntu chroot /host bash
```

**How rootless Docker closes this.** When `dockerd` runs as `honey`, the kernel imposes a user namespace: "root inside a container" maps to `honey` on the host, not UID 0. The mapping is established via subordinate UID/GID ranges in `/etc/subuid` and `/etc/subgid`:

```
honey:100000:65536
```

Under this mapping:
- Container UID 0 → host UID `honey`
- Container UID N (N ≥ 1) → host UID `100000 + N − 1`

A container escape can only do what `honey` can do on the host — own `/opt/<server>/`, read `/var/log/` (via the `adm` group for Vector), nothing else. `--privileged` and host volume mounts are still honored, but "host root" inside that context is just `honey` on the real host.

**Cowrie volume ownership.** Cowrie's container runs as UID 999. Because user namespace remapping shifts UIDs, the host-side volume directories must be owned by UID `100000 + 999 − 1 = 100998` (the subUID that maps to container UID 999), not by literal 999. `fragment.sh` computes this dynamically from `HONEY_SUBUID_START`.

**Port binding.** Rootless Docker uses userspace networking (via `pasta` on Ubuntu 24.04) rather than iptables NAT. Binding privileged ports (< 1024) requires `net.ipv4.ip_unprivileged_port_start = 0`, set in `server-config/99-hardening.conf`.

**Daemon lifecycle.** `loginctl enable-linger honey` causes systemd to maintain honey's user slice across reboots without a login session. The rootless daemon runs as a systemd user service (`systemctl --user start docker`) and is accessible at `unix:///run/user/<uid>/docker.sock`. All provisioning and redeploy scripts pass `DOCKER_HOST` pointing at this socket when invoking `docker compose` as honey.
