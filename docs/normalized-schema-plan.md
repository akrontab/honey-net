# Normalized Schema Generalization — Plan

Graduation of the **Detection & intel depth** theme's call for "a richer
normalized schema so cross-honeypot questions stay single-expression"
(`docs/!VISION.md`). It is also the **foundation** under
`docs/operationalizing-intel-plan.md` — that plan's phase 1 (schema promotion)
is the concrete first slice of this work.

Goal: make `{job="events"}` a real **contract** so that cross-honeypot questions,
dashboards, and alerts are honeypot-agnostic — and a new honeypot that fills the
contract appears in all of them with **zero dashboard edits**. The dashboards and
schema today are quietly shaped around Cowrie; this de-couples them.

This is a *plan*, not buildable tasks.

## Scope & timing — plan, not a build order

**Build trigger:** do this **before the next honeypot package lands** (the HTTP
pot in `docs/http-honeypot-plan.md`) and as the **first slice of
`operationalizing-intel-plan.md` phase 1**. Rationale: HTTP should be the first
pot built *into* the generalized contract rather than retrofitted, and the
operationalizing work (alerting on `login_success`, campaign selectors) is blocked
on the schema being rich enough. Doing it now avoids hand-coding Cowrie-shaped
dashboards a fourth time.

The core schema stays backward-compatible, so this is incremental, not a
big-bang migration — existing `{job="events"}` queries keep working.

## Current state — the coupling, measured

| Symptom | Evidence |
|---|---|
| Cross-cutting dashboards query raw Cowrie | **59 `eventid="cowrie.*"` refs across 9 dashboards** |
| Schema collapses distinctions | Cowrie `login.success` vs `login.failed` both → `event_type="login"`; **no `login_success` in `{job="events"}`** (Cowrie CLAUDE.md: "query the raw stream for that distinction") |
| Schema omits selectors | client fingerprint (HASSH), `dl_host`/`dl_filename`, arch, `database` are all Cowrie-raw or read-time regex |
| New pots under-count silently | a new honeypot doesn't appear in cross-cutting views until someone hand-edits them |
| The normalized stream is **lossy by design** | every pot's `remap` ends `if event_type == null { abort }` — unmapped `eventid`/`type` survive in raw but vanish from `{job="events"}`; a new pot's un-mapped events are silently absent, not wrong |
| No **sensor identity** in the schema body | per-sensor identity is the Loki `host` label (`${HONEYPOT_HOSTNAME}`), not an event field — two hosts running `honeypot="cowrie"` are indistinguishable inside the schema itself |
| `protocol` is **null on all but the first event** | Cowrie sets `protocol` only on `cowrie.session.connect`; login/command/download/session_end carry `null` (see `cowrie/CLAUDE.md`). Any `protocol=`-filtered cross-cutting query matches connects only |
| `timestamp` is the **honeypot's own clock** | copied verbatim from `raw.timestamp` (or `datetime.now()` in built-locally pots), not Loki ingest time — forgeable by a compromised pot |

Two distinct, **linked** problems:

- **A — dashboards on raw when they needn't be.** `credential-intelligence.json`
  is "credentials across all honeypots" but is a hand-stitched union of a Cowrie
  raw path (`{job="cowrie"} | eventid=~"cowrie.login.(failed|success)"`) and a
  MySQL raw path (`{job="mysql"} | event="login"`). `{job="events"} |
  event_type="login"` already covers Cowrie + Dionaea + MySQL.
- **B — the schema is too thin to carry the richness**, so dashboards are
  *forced* to raw. Fixing A requires enriching the schema first — same work, in
  order.

`telnet-overview.json` is the tell: 10 Cowrie eventids, because telnet *is*
Cowrie's other protocol. It should be `{job="events"} | protocol="telnet"`.

## Design: lean core + governed `meta`

Keep the existing flat **core** (the universal contract, unchanged for
backward-compatibility); push the missing richness into a nested **`meta`** object
each honeypot owns.

```json
{
  "timestamp":     "ISO-8601 UTC",
  "honeypot":      "cowrie",
  "protocol":      "ssh",
  "src_ip":        "1.2.3.4",
  "src_port":      54321,
  "session_id":    "...",
  "event_type":    "connect|login|command|query|download|session_end",
  "username":      "root",
  "password":      "...",
  "payload":       "...",
  "sample_sha256": "...",
  "meta": { /* governed, concept-named, capability-scoped */ }
}
```

- **Core is the contract** every event guarantees — unchanged, so existing
  queries and dashboards on core fields keep working untouched.
- **`meta` is a *governed vocabulary*, not a free bag.** The risk of a free bag is
  silent **key drift** (Cowrie writes `meta.username`, a later pot writes
  `meta.user`, the cross-cutting panel breaks quietly). So `meta` has two tiers:
  - **Standard capability keys** — a documented, concept-named vocabulary in
    `honey-pots/CLAUDE.md` that every pot with that capability **must** use.
  - **Pot-private keys** — genuinely unique fields only that pot's own dashboards
    read (e.g. Cowrie `arch`, ttylog reference).
- **Generalize names off Cowrie/SSH-isms.** Name the cross-protocol *concept*;
  each pot maps its protocol's mechanism into it.

### Standard `meta` vocabulary (initial)

| Capability (event_type) | `meta` key | Concept | Cowrie | MySQL | Dionaea | HTTP (planned) |
|---|---|---|---|---|---|---|
| `login` | `login_success` | auth outcome | success/failed eventid | always-accept | n/a | form/basic result |
| `login` | `auth_method` | how they authed | password / pubkey | native_password | — | basic / form |
| `connect` | `client_fingerprint` | client identity | **HASSH** | — | — | **JA3/JA4** |
| `connect` | `client_version` | client banner | `cowrie.client.version` | — | — | User-Agent |
| `download` | `url` | fetch URL | `raw.url` | — | `raw.url` | upload origin |
| `download` | `dl_host` | staging infra | (regex today) | — | (regex) | — |
| `download` | `dl_filename` | payload name | (regex today) | — | (regex) | upload name |
| `command` | `command_success` | did it run | input/failed eventid | — | — | — |
| `query` | `database` | target DB | — | `raw.database` | — | — |

`meta` is flattened by Loki's `| json` on `_`, so queries read naturally:
`{job="events"} | json | meta_login_success="true"`.

### The hard rule (keeps it from re-coupling)

- **Cross-cutting dashboards and alerts query `{job="events"}` only.** Anything
  reaching into `{job="<pot>"} | eventid=...` belongs in a **per-protocol**
  dashboard. Per-protocol dashboards (`cowrie-overview`, `mysql-overview`) staying
  raw is correct — that's their job.

## Production layer: wrapper scripts & Docker config

The schema is only as good as what the **production layer** hands it. "Generalizing
the schema" is really *governing what each honeypot package emits* — so this plan
has to reach down into the package internals (`honey-pots/<pot>/deploy/`), not just
the Vector `remap`. Two archetypes produce the raw events, and they offer different
enforcement points:

- **Built-locally pots own their log schema outright** (`mysql`, `smb`, `ftp`,
  planned `http`). The honeypot *is* our code — e.g. `mysql/deploy/honeypot/logger.py`
  `log_event()` writes the JSONL the `remap` later reads. For these, a standard
  `meta` field is cleanest to mint **at the source** (the logger), with the `remap`
  just forwarding it; the contract is enforceable where the event is born.
- **Third-party pots are config- and sidecar-wrapped** (`cowrie`, `dionaea`). We
  don't own the event shape; we *steer* it. Cowrie's `etc/cowrie.cfg` redirects
  `output_jsonlog.logfile` to the conventional `./volumes/logs/cowrie.json`; a
  `capture-writer` sidecar tails that log to mint `.capture.json` provenance the
  upstream never emitted; `cowrie-ext/` adds a key-harvester. For these, a standard
  `meta` key must be **derived in the `remap`** from whatever the upstream happens to
  log — the harder, drift-prone path. (Cowrie's null-`protocol`-downstream problem in
  the table above is exactly this: the upstream only states protocol once.)

**The Docker layer is the contract's plumbing, and it's near-identical across pots**
(conventions in `honey-pots/CLAUDE.md`):

- `docker-compose.yml` bind-mounts `./volumes/logs` into the honeypot (read-write)
  and into the `vector` sidecar at `/logs/<pot>:ro` — that shared volume **is** the
  hand-off from honeypot to normalizer. A new `meta` field changes nothing here;
  the plumbing is already schema-agnostic.
- Every Loki sink stamps `labels.host = "${HOSTNAME}"` (from `HONEYPOT_HOSTNAME`) and
  the events sink adds `labels.honeypot`. **These two labels are the sensor key**;
  the schema body has no sensor identity. The generalization should treat
  `(honeypot, host)` as the unit, and template `sensor-health` on `host` — not just
  `honeypot` — so a second cowrie sensor is visible, not merged.
- The `remap` transform is the actual normalizer — and it is **copy-pasted into every
  pot's `vector.toml`** (5 today, no shared VRL include). "The contract" therefore
  exists as five independently hand-maintained transforms. This is *why* `meta` key
  drift is the default outcome rather than an edge case, and it is the concrete thing
  open question 1 (enforcement) is about.

**Implication for this plan:** phase 2 ("enrich the Vector transforms") is really
*N package edits*, and for built-locally pots part of the enrichment may belong in the
honeypot's own logger, not the `remap`. The vocabulary doc in `honey-pots/CLAUDE.md`
(phase 1) is the only thing standing between five transforms and silent divergence —
documentation is load-bearing until question 1 is answered.

## Migration — gentle, because core is unchanged

| Dashboard class | Action |
|---|---|
| Per-protocol (`cowrie-overview`, `mysql-overview`, `telnet-overview`→protocol filter) | Keep raw; rename telnet to a protocol view |
| Cross-cutting on core fields already | No change |
| Cross-cutting forced to raw for now-in-`meta` fields | Migrate to `{job="events"}` + `meta_*` |

**Worked example — `credential-intelligence.json`:** the two SSH stat/table
panels (`{job="cowrie"} | eventid=~"cowrie.login..."`) and the separate MySQL
panels (`{job="mysql"} | event="login"`) collapse to one honeypot-agnostic query
`{job="events"} | json | event_type="login"` (+ `meta_login_success` for the
success/failure split), which also picks up Dionaea and every future pot for free.

## Self-describing payoff

This extends the self-describing-package model (`docs/!DESIGN.md`) to the
observability layer: a new honeypot that fills the core contract + standard `meta`
keys **automatically** appears in every cross-cutting dashboard, alert, and the
campaign tooling — no dashboard edits. Today a new pot needs hand-written panels
*and* silently under-counts in the cross-cutting views.

## Relationship to other plans

- **`operationalizing-intel-plan.md`** — its phase 1 (schema promotion) is the
  first slice of this. `login_success` is required for that plan's "successful
  auth" alert; `dl_host`/`client_fingerprint`/family are its campaign selectors
  *and* novelty-alert keys. That plan should not start before this lands.
- **`http-honeypot-plan.md`** — HTTP should be the first pot authored against the
  generalized contract (JA3/JA4 → `client_fingerprint`, User-Agent →
  `client_version`), proving the vocabulary generalizes beyond SSH.
- **`malware-catalog`** — the download `meta` keys (`url`/`dl_host`) pair with the
  catalog provenance join in the operationalizing plan.

## Phases

1. **Define the contract.** Document core + standard `meta` vocabulary in
   `honey-pots/CLAUDE.md` (concept-named, capability-scoped); mark `meta`
   governance (standard vs pot-private).
2. **Enrich the Vector transforms.** Add `.meta` to each pot's `remap`
   (`cowrie`: `login_success`, `client_fingerprint` from HASSH, `client_version`,
   `dl_host`/`dl_filename`; `mysql`: `database`; `dionaea`: `dl_host`/`dl_filename`).
   Per-honeypot `CLAUDE.md` documents its `meta` mapping.
3. **Migrate cross-cutting dashboards** to `{job="events"}` + `meta_*`
   (`credential-intelligence`, `campaign-tracking`, `session-analysis`,
   `attacker-drilldown`, `sensor-health`). Drive `sensor-health` off a `honeypot`
   template variable so new pots auto-appear.
4. **Re-scope `telnet-overview`** to `{job="events"} | protocol="telnet"`. **Blocked
   on a `remap` fix:** today Cowrie populates `protocol` only on the connect event, so
   this selector would match connects and drop every telnet login/command. Carry
   `protocol` onto all events first — either upstream (Cowrie config emitting it per
   event), via a stateful Vector `reduce`/lookup keyed on `session_id`, or promote
   `protocol` to a per-session enrichment. Resolve open question 5 before doing this.
5. **Enforce the rule** — note in `honey-pots/CLAUDE.md` and the dashboard
   checklist that cross-cutting panels use `{job="events"}` only.

## Open questions (resolve before BACKLOG)

1. **`meta` governance enforcement** — the contract lives as five copy-pasted
   `remap` transforms with no shared VRL (see *Production layer*), so drift is the
   default. Documentation-only, or a lightweight schema/lint check (e.g. a test that
   asserts each pot's `remap` — or, for built-locally pots, its logger — emits the
   declared standard keys for its capabilities)? *Lean: doc the vocabulary now, add a
   test when the third pot's `meta` lands.*
2. **Fingerprint generalization** — is `client_fingerprint` one field with a
   `meta.fingerprint_type` discriminator (`hassh`/`ja3`/`ja4`), or separate keys?
   *Lean: one field + type discriminator.*
3. **`payload` vs `meta.url`** — keep `payload=url` on downloads for
   back-compat *and* add `meta.url`/`meta.dl_host`, or move URL fully into `meta`?
   *Lean: keep `payload` for back-compat, prefer `meta` in new dashboards.*
4. **Retro-fill** — re-emit `meta` for historical events (not possible past Loki's
   30-day retention) or accept the discontinuity at cutover? *Lean: accept it.*
5. **Protocol on every event** — how does `protocol` get onto non-connect events so
   `protocol`-filtered cross-cutting queries (and the telnet re-scope) work? Upstream
   per-event emission, a stateful Vector `reduce` keyed on `session_id`, or a
   session-join at read time? *Lean: stateful `reduce` in Vector — keeps the read path
   simple and fixes it for every pot at once.*
6. **Sensor identity** — is `(honeypot, host)` enough to identify a sensor for
   multi-operator/multi-sensor views, or does the schema need an explicit `sensor`/
   `server` field in the body (not just the `host` label)? *Lean: labels suffice;
   revisit if `docs/multi-operator-plan.md` needs body-level attribution.*

## Graduation to BACKLOG

- [ ] Core + standard `meta` vocabulary documented in `honey-pots/CLAUDE.md`
- [ ] `cowrie` `vector.toml` emits `meta` (login_success, client_fingerprint, client_version, dl_host, dl_filename) + CLAUDE.md mapping
- [ ] `mysql` `vector.toml` emits `meta.database` + CLAUDE.md mapping
- [ ] `dionaea` `vector.toml` emits `meta.dl_host`/`dl_filename` + CLAUDE.md mapping
- [ ] Cross-cutting dashboards migrated to `{job="events"}` + `meta_*`
- [ ] `sensor-health` templated on `host` (not just `honeypot`) so a second sensor of the same type is visible
- [ ] `protocol` carried onto all events (per question 5) — prerequisite for the telnet re-scope
- [ ] `telnet-overview` re-scoped to a `protocol="telnet"` view
- [ ] Dashboard checklist updated with the cross-cutting `{job="events"}`-only rule
