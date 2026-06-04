# Wrapping an Upstream Honeypot — Plan

How to add a honeypot **whose code we don't control** (a third-party project
distributed as a PyPI package, a git repo, or a prebuilt image) to the net.

Status: **process defined + first reference package built** (`honey-pots/heralding/`).
Heralding is the worked example, not a committed member of the net — it is *not*
in `honey-net.json`. Build a real wrapped pot at the next genuine trigger.

## The surprising finding: the contract already supports this

The package system was designed around first-party pots (we own the `Dockerfile`
and the log schema), but almost none of that is actually load-bearing. A package
is discovered structurally, and the two places that could have hard-coded "we
built this image" do not:

- `lib/package.py:component_build_services()` returns a build step **only for
  services that declare a `build:` block**. An `image:`-only service yields `[]`,
  so `provision.py` / `redeploy.py` simply skip the build and go straight to
  `up -d`. (See `honey-pots/CLAUDE.md` build-in-sequence rule.)
- `assemble_honeypot_package()` strips and re-merges the `vector` service and
  re-roots log mounts **regardless of how the pot's own image is sourced**.

So a wrapped upstream pot needs **zero changes** to Terraform, `server-config/`,
the root scripts, or the assembler. It is the same self-describing package
contract — the work moves entirely into three files the package already owns:
the compose service, the Vector adapter, and (sometimes) a sidecar.

## What actually changes vs. a first-party pot

| Concern | First-party | Wrapped upstream |
|---|---|---|
| **Image sourcing** | `build: ./svc` (our Dockerfile) | pinned image **or** thin Dockerfile pinning upstream (see modes below) |
| **Log schema** | we emit our own JSON → trivial remap | foreign format at a foreign path → the Vector remap becomes a real **adapter** |
| **Log format** | JSON we control | maybe JSON, maybe CSV / text / syslog / sqlite / stdout-only |
| **Sample capture** | we write `<sha256>` to `/samples` | upstream writes whatever, wherever → may need a canonicalising sidecar |
| **Trust** | we read every line | new supply-chain surface → **pin** and treat the image as hostile |

Everything else is unchanged: `{job="events"}` schema, the fragment/port/ownership
rules, the `meta` vocabulary, Loki labels, dashboards.

## Image sourcing — two modes

**Mode A — pinned prebuilt image.** Use when upstream publishes a maintained
image. Pin **by digest**, never a moving tag:

```yaml
services:
  foo:
    image: ghcr.io/vendor/foo@sha256:<digest>   # immutable; survives tag re-pushes
```

**Mode B — thin Dockerfile pinning an upstream version.** Use when upstream ships
only source / a PyPI package / a `Dockerfile` (the common case — most honeypots
have no maintained image). We don't write the code; we pin the exact upstream
version. This slots into the existing build-in-sequence path automatically:

```dockerfile
FROM python:3.9-slim-bullseye          # match upstream's tested base
RUN pip install --no-cache-dir foo==1.2.3   # pinned upstream release
```

Prefer Mode A's digest when one exists. Mode B's `==version` is a soft pin;
**hash-locking** it (`pip install --require-hashes -r locked.txt`, or a digest on
the base image) is the hardening step — deferred until a wrapped pot is promoted
into `honey-net.json` (see Deferred).

The reference pot (`heralding`) is **Mode B**: `pip install heralding==1.0.7`.

## The adapter — ingesting a log we can't reformat

The honeypot emits its own format at its own path; we cannot patch its code to
write our schema. The Vector `remap` is where the foreign shape becomes the
normalized event. Pick the source strategy by what the upstream emits:

| Upstream emits | Vector source | Adapter work in the remap |
|---|---|---|
| **JSON file** (alien field names) | `file` | `parse_json!` then re-key — same shape as first-party, just different field names |
| **CSV file** (e.g. heralding `log_auth.csv`) | `file` | `parse_csv!`, `abort` the header row, map **positionally** |
| **plain text / key-value** | `file` | `parse_regex!` / `parse_grok!` / `parse_key_value!` first |
| **stdout only** (no file) | `docker_logs` | parse the line, then remap |
| **syslog** | `syslog` | already structured; re-key |
| **sqlite / binary DB** | — | **sidecar** tails the DB → writes JSONL we own → `file` (don't teach Vector the DB) |

Two streams, same as every pot:

- **raw** `{job="<pot>"}` — ship the richest native log untouched (forensics).
- **normalized** `{job="events", honeypot="<pot>"}` — the adapter output.

Fill the standard `meta` keys for each capability the pot has (the table in
`honey-pots/CLAUDE.md`) so the wrapped pot lands in every cross-cutting dashboard
with zero dashboard edits — **the whole point of the schema contract.** The
adapter, not the upstream, is responsible for spelling those keys correctly.

### Worked CSV adapter (heralding)

`log_auth.csv` is one row per credential attempt:
`timestamp,auth_id,session_id,source_ip,source_port,destination_port,protocol,username,password`.
The remap parses the row, drops the header, and emits a normalized `login`:

```coffee
row = parse_csv!(string!(.message))
if row[0] == "timestamp" { abort }     # header line
. = {
  "timestamp":  row[0],
  "honeypot":   "heralding",
  "protocol":   downcase(string!(row[6])),  # ftp|ssh|http|... — varies per row
  "src_ip":     row[3],
  "src_port":   to_int(row[4]) ?? null,
  "session_id": row[2],
  "event_type": "login",
  "username":   row[7],
  "password":   row[8],
  "payload":    null, "sample_sha256": null,
  "meta": { "login_success": "false", "auth_method": "password" },
}
```

`login_success` is always `false` — heralding is a pure credential collector, it
never grants access. `protocol` varies per row, which is exactly what makes a
multi-protocol wrapped pot a good schema stress-test.

## Sample capture (when the upstream grabs binaries)

If the wrapped pot downloads payloads, bind-mount its drop path to
`../inbox/<name>:/samples` and, if its filenames/sidecars don't match the
provenance contract, add a **capture-writer-style sidecar** (Cowrie already has
one — copy `honey-pots/cowrie/deploy/capture-writer/`) that canonicalises to
`<sha256>` + `<sha256>.capture.json`. The `metadata` + `malware-sender` addons
then pick them up unchanged. Heralding captures no binaries, so the reference
pot skips this — the sidecar pattern is documented, not built here.

## What's unchanged (do not re-invent)

- `honey-net.json` entry: identical shape (`name/type/ssh_key/honeypots/ports`).
- `fragment.sh`: same responsibilities (open UFW ports, `mkdir`+`chown honey:honey`
  the log dir, build-in-sequence, terminal-or-not `up -d`).
- Ownership/port gotchas: a wrapped pot publishing low ports relies on the same
  rootless **pasta** port driver from `server-config/` that ftp/smb/http already
  use to preserve attacker `src_ip` — no per-pot work.
- Live update: `redeploy --server NAME` works as-is (empty build list for Mode A;
  builds the thin Dockerfile for Mode B). Bumping a Mode-A digit or Mode-B version
  is a compose/Dockerfile edit + `redeploy`.

## Checklist diff (vs. the first-party checklist in honey-pots/CLAUDE.md)

- [ ] Choose **Mode A** (pinned digest) or **Mode B** (thin Dockerfile + pinned version)
- [ ] `deploy/<svc>/Dockerfile` **only if Mode B** (thin: `FROM` + install pinned version)
- [ ] Upstream config file if it needs one (e.g. heralding's `heralding.yml`),
      mounted **read-only**, with log paths pointed at the mounted volume
- [ ] `deploy/vector/vector.toml` — **adapter** remap for the foreign format
      (everything else in the checklist is identical to a first-party pot)
- [ ] Capture-writer sidecar **only if** the upstream captures binaries
- [ ] Pin verification on first deploy: confirm the running version matches the pin

## Deferred (build at trigger, not now)

- **Hash-locked pins.** `--require-hashes` / base-image digest for Mode B, and a
  recorded digest for Mode A — do this when a wrapped pot enters `honey-net.json`.
- **Adapter regression test.** A tiny fixture-line → expected-event test for the
  CSV/regex adapters (foreign formats drift between upstream releases; a pin bump
  should fail loudly if columns move). Pairs with the deferred `meta` lint in
  `normalized-schema-plan.md` Q1.
- **Promoting heralding** (or any wrapped pot) into the net: add the
  `honey-net.json` entry, generate the SSH key, hash-lock the pin, add a Grafana
  dashboard, `provision --server <name>`.
- **stdout-only / sqlite reference.** If a future wrapped pot needs the
  `docker_logs` source or a DB-tailing sidecar, capture that variant here.
