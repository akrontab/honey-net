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
