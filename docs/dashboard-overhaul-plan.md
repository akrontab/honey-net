# Dashboard Overhaul — Plan

Graduation of the **Operationalizing the intel** theme in `docs/!VISION.md`: the
**visualization surface** that turns the normalized `{job="events"}` stream into
the screens an operator actually watches and hunts in. A complete overhaul of
today's organically-grown dashboard set, rebuilt onto the schema **contract** in
`honey-pots/CLAUDE.md` so cross-cutting views are honeypot-agnostic and a new pot
appears in them with zero dashboard edits.

This plan **owns the entire dashboard surface**. `docs/operationalizing-intel-plan.md`
owns the non-visual actions (alert rules, digest job, outbound publishing, the
catalog provenance join) and *references this plan* for anything that renders —
including the campaign pivot dashboard and event-timeline session replay it
specifies, which are built here, to these conventions.

This is a *plan*, not buildable tasks.

## Scope & timing — plan, not a build order

**Build trigger — fired.** The normalized-schema contract has landed (lean core +
governed `meta`; `meta_login_success` / `command_success` / `url` / `dl_host` /
`dl_filename` / `database` now emitted — see `honey-pots/CLAUDE.md`), and the
current dashboards are Cowrie-coupled and due for replacement. The contract now
exists to build against; rebuilding the dashboards onto it avoids hand-shaping
Cowrie-coupled panels a fourth time.

Unlike the schema (which stayed backward-compatible), dashboards are being
**replaced**, so this is a clean rebuild, not an incremental migration. Old
dashboards keep working until each is superseded.

## Current state — why overhaul

| Symptom | Evidence |
|---|---|
| No taxonomy | ~15 dashboards grown organically (overview / credential / campaign / session / attacker / malware / host + per-protocol), with overlap and no clear "where do I start" |
| Cross-cutting dashboards query raw Cowrie | the coupling measured in `normalized-schema-plan.md` (59 `eventid="cowrie.*"` refs across 9 dashboards) — breaks the hard rule and under-counts every non-Cowrie pot |
| Read-time extraction now redundant | `dl_host`/`dl_filename` are `regexp`'d from the URL at panel read-time; the contract now emits `meta_dl_host`/`meta_dl_filename` directly |
| Organized by data source, not by use | there is no "triage vs. hunt vs. operate" shape — an operator can't tell which board to open for which job |
| Sensors merge | `sensor-health` keys on `honeypot`, not `(honeypot, host)`; two sensors of the same type are indistinguishable (the schema plan's sensor-identity gap, on the read side) |
| New pots are invisible | a new honeypot (e.g. the just-shipped HTTP pot) does not appear in any cross-cutting view until someone hand-edits panels |

## Design: a two-axis taxonomy

**Primary axis — workflow tiers.** The heavily-used set, built first, all
cross-cutting on `{job="events"}` and honeypot-agnostic:

| Tier | Question it answers | Dashboards (initial) |
|---|---|---|
| **Triage** | "what's happening right now — is anything wrong?" | Situational **Overview** (event volume by `event_type` / `protocol` / sensor, live activity feed, current alert state) |
| **Hunt** | "dig into attacker behavior, find campaigns" | **Campaign pivot** (selector template var → co-occurrence), **Session explorer/replay** (event-timeline by `session_id`), **Credential intel** (`meta_login_success`), **Download / infra intel** (`meta_dl_host`/`dl_filename`) |
| **Operate** | "is the fleet healthy?" | **Fleet / sensor health** (per `(honeypot, host)`, sensor-dark), **Host security** (`{job="auth"}`/`syslog`, fail2ban), **Pipeline / ingest health** (Loki/Vector throughput, disk) |

**Secondary axis — intel-domain / per-protocol deep dives.** Used in specific
scenarios to *augment* the tiers; these live on the **raw** `{job="<pot>"}`
stream, where per-protocol `eventid` detail correctly belongs:

| Domain | Deep-dive dashboard | Stream |
|---|---|---|
| SSH / Telnet | Cowrie deep-dive (+ telnet protocol view) | raw `cowrie` |
| MySQL | MySQL query / decoy intel | raw `mysql` |
| SMB / FTP | Dionaea deep-dive | raw `dionaea` |
| HTTP | HTTP deep-dive | raw `http` |
| Malware | Sample / catalog analysis | catalog API + `{job="events"}` |

**The two axes are linked by drill-down.** A workflow-tier tile carries a Grafana
data link into the matching per-protocol deep-dive for forensic detail. Workflow
tiers stay honeypot-agnostic (the hard rule); deep-dives are where raw `eventid`
lives. This is the self-describing payoff applied to observability: a new pot that
fills the contract appears in **every workflow tier for free** and only optionally
adds its own deep-dive.

## Conventions — the dashboard contract

- **Cross-cutting (workflow tiers) query `{job="events"}` only** — the hard rule in
  `honey-pots/CLAUDE.md`. Per-protocol deep-dives may use the raw stream; that is
  their job.
- **Consume `meta_*` directly** (`meta_login_success`, `meta_dl_host`,
  `meta_command_success`, `meta_database`, …) — no read-time `regexp` for fields the
  contract now emits.
- **Template fleet/health views on both `honeypot` and `host`** so a second sensor
  of the same type is visible, not merged.
- **Provisioned** as JSON under `log-stack/deploy/grafana/provisioning/dashboards/`,
  grouped into Grafana **folders mirroring the tiers** (Triage / Hunt / Operate /
  Deep-dives). Single Loki datasource uid `loki`; stable dashboard uids.

## Relationship to other plans

- **`normalized-schema-plan.md`** — provides the contract this consumes. Its
  **deferred Q5** (carry `protocol` onto every event; cowrie `client_fingerprint`/
  `client_version`) blocks a true `protocol`-filtered cross-cutting tile *and* the
  telnet protocol view — both wait on that spike.
- **`operationalizing-intel-plan.md`** — owns alert rules, the digest job, outbound
  publishing, and the catalog provenance join. This plan **builds the dashboards it
  references**: the campaign pivot (its L1 instrument) → **Hunt**; event-timeline
  session replay → **Hunt**; the sensor-dark surface → **Operate**. Live alert
  *state* is surfaced in **Triage**. The two plans dovetail at the render seam.
- **`malware-catalog/PLAN.md`** — the Malware deep-dive joins catalog data; the
  provenance join (operationalizing phase 5) enriches session ↔ sample pivots in
  Hunt.
- **`http-honeypot-plan.md`** — already shipped; it fills the contract, so it gets
  Triage/Operate coverage for free once these tiers exist, plus an HTTP deep-dive.

## Migration map — current dashboards → new taxonomy

| Today | Disposition |
|---|---|
| `normalized-events` | → rebuilt as the **Triage / Overview** landing dashboard |
| `credential-intelligence` | → **Hunt / Credential intel**, on `{job="events"}` + `meta_login_success` |
| `campaign-tracking` | → **Hunt / Download & infra intel** (+ Campaign pivot), `meta_dl_host`/`dl_filename` |
| `session-analysis`, `attacker-drilldown` | → **Hunt / Session explorer**, with `session_id` replay |
| `attacker-fingerprinting` | → folds into **Hunt** pivot (blocked on Q5 fingerprint fields) |
| `malware-analysis` | → **Deep-dive / Malware** (catalog-joined) |
| `sensor-health` | → **Operate / Fleet health**, re-keyed on `(honeypot, host)` |
| `host-security` | → **Operate / Host security** |
| `cowrie-overview`, `cowrie-commands` | → **Deep-dive / Cowrie** (stay raw — correct) |
| `mysql-overview`, `mysql-query-intel` | → **Deep-dive / MySQL** (stay raw — correct) |
| `telnet-overview` | → **Deep-dive / Cowrie** telnet protocol view (blocked on Q5 `protocol`-on-all-events) |

## Phases

1. **Triage tier** — the situational **Overview**, on `{job="events"}`; becomes the
   landing dashboard, replacing `normalized-events`.
2. **Operate tier** — Fleet/sensor health templated on `(honeypot, host)` (fixes the
   merge), Host security, Pipeline/ingest health.
3. **Hunt core** — Credential intel and Download/infra intel rebuilt on `meta_*`.
4. **Hunt analytical** — Campaign pivot (operationalizing L1) + event-timeline
   session replay; coordinated with `operationalizing-intel-plan.md`.
5. **Per-protocol deep-dives** — Cowrie, MySQL, Dionaea/SMB-FTP, HTTP; wire
   drill-down data links from the workflow tiers.
6. **(Blocked on schema Q5)** protocol-filtered cross-cutting tile + telnet protocol
   view + fingerprint panels.
7. **Cut over & document** — deprecate superseded dashboards; add the dashboard
   contract to the `honey-pots/CLAUDE.md` new-pot checklist and `log-stack/CLAUDE.md`.

## Open questions (resolve before BACKLOG)

1. **Grafana folders mirror the tiers?** *Lean: yes — Triage / Hunt / Operate /
   Deep-dives as folders; it makes "where do I start" answer itself.*
2. **One parametrized Hunt pivot or several focused boards?** *Lean: one pivot
   dashboard (template var on the tight selectors) plus focused Credential and
   Download boards; the pivot is the learning instrument, the others are standing
   views.*
3. **Triage landing — rebuild `normalized-events` or start fresh?** *Lean: a fresh
   Overview; `normalized-events` predates the contract.*
4. **Drill-down mechanism** — Grafana data links on tiles vs. dashboard links.
   *Lean: data links on tiles (carry the clicked selector into the deep-dive).*
5. **Alert-state in Triage** — native Grafana alert-list panel vs. custom. *Lean:
   native alert-list; depends on `operationalizing-intel` phase 2 landing alert
   rules.*
6. **Dashboard testing/lint in CI** — JSON validity + "cross-cutting uses
   `{job="events"}` only" check. *Lean: defer to the Operational-maturity CI work;
   document the rule now.*

## Graduation to BACKLOG

The Triage + Operate tiers can graduate as soon as Q1/Q3 are answered; the Hunt
analytical pieces coordinate with `operationalizing-intel`; the Q5-blocked items
wait on that spike.

- [ ] Triage / Overview dashboard on `{job="events"}` (replaces `normalized-events`)
- [ ] Operate / Fleet health re-keyed on `(honeypot, host)`; Host security; Pipeline health
- [ ] Hunt / Credential intel + Download & infra intel on `meta_*`
- [ ] Hunt / Campaign pivot + event-timeline session replay (with `operationalizing-intel`)
- [ ] Per-protocol deep-dives (Cowrie, MySQL, Dionaea, HTTP) + drill-down data links
- [ ] (Q5) protocol-filtered tile + telnet protocol view + fingerprint panels
- [ ] Deprecate superseded dashboards; dashboard contract added to `honey-pots/CLAUDE.md` + `log-stack/CLAUDE.md`
