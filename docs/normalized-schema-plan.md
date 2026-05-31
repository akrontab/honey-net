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
4. **Re-scope `telnet-overview`** to `{job="events"} | protocol="telnet"`.
5. **Enforce the rule** — note in `honey-pots/CLAUDE.md` and the dashboard
   checklist that cross-cutting panels use `{job="events"}` only.

## Open questions (resolve before BACKLOG)

1. **`meta` governance enforcement** — documentation-only, or a lightweight
   schema/lint check (e.g. a test that asserts each pot's `remap` emits the
   declared standard keys for its capabilities)?
2. **Fingerprint generalization** — is `client_fingerprint` one field with a
   `meta.fingerprint_type` discriminator (`hassh`/`ja3`/`ja4`), or separate keys?
   *Lean: one field + type discriminator.*
3. **`payload` vs `meta.url`** — keep `payload=url` on downloads for
   back-compat *and* add `meta.url`/`meta.dl_host`, or move URL fully into `meta`?
   *Lean: keep `payload` for back-compat, prefer `meta` in new dashboards.*
4. **Retro-fill** — re-emit `meta` for historical events (not possible past Loki's
   30-day retention) or accept the discontinuity at cutover? *Lean: accept it.*

## Graduation to BACKLOG

- [ ] Core + standard `meta` vocabulary documented in `honey-pots/CLAUDE.md`
- [ ] `cowrie` `vector.toml` emits `meta` (login_success, client_fingerprint, client_version, dl_host, dl_filename) + CLAUDE.md mapping
- [ ] `mysql` `vector.toml` emits `meta.database` + CLAUDE.md mapping
- [ ] `dionaea` `vector.toml` emits `meta.dl_host`/`dl_filename` + CLAUDE.md mapping
- [ ] Cross-cutting dashboards migrated to `{job="events"}` + `meta_*`
- [ ] `sensor-health` driven by a `honeypot` template variable
- [ ] `telnet-overview` re-scoped to a `protocol="telnet"` view
- [ ] Dashboard checklist updated with the cross-cutting `{job="events"}`-only rule
