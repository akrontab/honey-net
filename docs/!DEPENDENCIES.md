# Plan Dependencies

Tracks how the plan files in `docs/` (and `malware-catalog/PLAN.md`) depend on
one another, so sequencing is explicit and nothing gets built out of order. This
is the **middle layer** of the altitude pipeline in `docs/!VISION.md`:

```
VISION.md  ──►  plan files  ──►  BACKLOG.md  ──►  DESIGN.md / code
(themes)        (this graph)     (scoped tasks)   (built)
```

Each plan graduates from a VISION theme; this file records the edges *between*
plans. Update it whenever a plan is added, graduates to `BACKLOG.md`, or its
dependencies change.

## Edge types

- **`requires →`** — *hard*: the target must land first; the plan says so
  explicitly ("do not start before…", "relies on…").
- **`enables →`** — *hard*, reverse of `requires`: what this plan unblocks.
- **`after →`** — recommended ordering, not a hard block.
- **`uses → / feeds →`** — *soft*, directional: consumes or supplies, but can
  proceed in parallel; coordinate at the seam.
- **`pairs ↔`** — *soft*, bidirectional: the two plans inform each other.

## Dependencies by plan

Each entry is self-contained — edges are shown from both ends, so you can read
one plan without tracing the whole graph.

```
normalized-schema-plan        (keystone — depends on nothing)
  enables  → operationalizing-intel   (hard: its phase 1)
  enables  → dashboard-overhaul       (hard: the meta_* contract it consumes)
  enables  → http-honeypot            (recommended: author into the contract)
  enables  → canary-credentials       (soft: pubkey-fingerprint replay match; core creds already present)
  pairs    ↔ malware-catalog          (soft: download `meta` ↔ provenance)

operationalizing-intel-plan
  requires → normalized-schema        (hard: phase 1 prerequisite)
  enables  → alerting                 (soft: campaign correlation defines campaign-novelty rule)
  uses     → malware-catalog          (soft: campaign selectors — family/IOCs/imphash)
  pairs    ↔ dashboard-overhaul       (soft: this owns actions, that owns rendering — pivot/replay/alert-state seam)
  pairs    ↔ incident-response        (soft: alerting, egress/breakout)
  uses     → high-interaction-pots    (soft: deep sessions feed TTP characterization §3a)
  pairs    ↔ canary-credentials       (soft: canary replay = campaign-grade signal; bait-fetch→replay join)

dashboard-overhaul-plan       (operationalizing theme — the visualization surface)
  requires → normalized-schema        (hard: consumes the meta_* contract)
  pairs    ↔ operationalizing-intel   (soft: owns rendering for its pivot/replay/alert-state)
  pairs    ↔ alerting                 (soft: P1 detection dashboard folds into the Triage tier)
  uses     → malware-catalog          (soft: malware deep-dive)

alerting-plan                 (operationalizing theme — graduated out of operationalizing-intel)
  requires → normalized-schema        (soft: rules read meta_*; HASSH novelty blocked on Q5)
  uses     → malware-catalog          (soft: new_sample free; first-seen registry; family novelty)
  pairs    ↔ operationalizing-intel   (soft: campaign-novelty needs its correlation; digest = digest-tier sink)
  pairs    ↔ dashboard-overhaul       (soft: P1 detection dashboard → Triage tier)
  pairs    ↔ incident-response        (soft: security-model violations / honeypot-egress capture gap)
  pairs    ↔ canary-credentials       (soft: hosts the deception-tripwire rule class)
  pairs    ↔ high-interaction-pots    (soft: its Phase 2 egress capture lands the deferred breakout rule)

http-honeypot-plan
  after    → normalized-schema        (recommended: built into the generalized contract)
  feeds    → malware-catalog          (soft: supplies uploaded samples)
  pairs    ↔ canary-credentials       (soft: _BAIT is the first planting site)

canary-credentials-plan       (Detection & intel depth — deception/honeytokens)
  after    → normalized-schema        (soft: replay match reads core creds; pubkey match blocked on its Q5)
  uses     → malware-catalog          (soft: canary registry table, colocated with the first-seen novelty registry)
  pairs    ↔ alerting                 (soft: deception-tripwire = a new rule class on its {job="detections"} contract)
  pairs    ↔ operationalizing-intel   (soft: canary replay = campaign-grade signal; bait-fetch→replay join)
  pairs    ↔ http-honeypot            (soft: _BAIT is the first planting site + registry producer)

high-interaction-pots-plan    (Detection & intel depth — interaction depth, not breadth)
  feeds    → operationalizing-intel   (soft: deep sessions = richest TTP-characterization + TTY-replay input)
  pairs    ↔ alerting                 (soft: Phase 2 egress capture lands the deferred honeypot-egress breakout rule)
  pairs    ↔ incident-response        (soft: breakout expected here; egress/response overlap)
  pairs    ↔ aws-eks-migration-plan   (soft: VM-vs-orchestration isolation trade-off informs isolation tech)

malware-catalog/PLAN          (mostly standalone — depends on nothing)
  enables  → operationalizing-intel   (soft: campaign L2/L3 selectors)
  pairs    ↔ http-honeypot            (soft: consumes its samples)
  feeds    → canary-credentials       (soft: hosts the canary registry table)

multi-operator-plan           (depends on nothing)
  enables  → incident-response        (hard: delivers the single rotatable anchor)
  pairs    ↔ aws-eks-migration-plan   (soft: per-provider break-glass)

incident-response-plan
  requires → multi-operator           (hard: the single rotatable anchor)
  pairs    ↔ operationalizing-intel   (soft: alerting / self-healing)
  pairs    ↔ aws-eks-migration-plan   (soft: break-glass console differs per provider)
  pairs    ↔ high-interaction-pots    (soft: breakout expected here; egress/response overlap)

aws-eks-migration-plan        (standalone "Maybe" — depends on nothing)
  pairs    ↔ multi-operator           (soft: break-glass)
  pairs    ↔ high-interaction-pots    (soft: isolation trade-off informs isolation tech)

deployment-plan               (Operational maturity — the change-delivery pattern; cross-cutting)
  pairs    ↔ incident-response        (soft: intentional push ↔ unintentional recovery / self-healing)
  uses     → multi-operator           (soft: supplies live-config delivery for operator-set changes)
  feeds    → alerting                 (soft: secret-push path for Phase 2 channel tokens)
  enables  → reconfigure              (its Phase 2 graduated into a child plan)

reconfigure-plan              (Operational maturity — graduated out of deployment-plan Phase 2)
  after    → deployment-plan          (implements Phase 2; the Phase 1 pattern is already shipped)
  feeds    → deployment-plan          (Phase 4 verification gate consumes its composer tests + live path)
  feeds    → multi-operator           (soft: live-config delivery mechanism for operator-set changes, gap 7)
  pairs    ↔ secrets-management       (soft: borders gap 6 — secret/.env push kept deliberately separate)
```

## Dependency table

**Status** values: `draft` (plan only) · `building` (partially shipped) · `built`
(graduated and shipped; residual items noted) · `shelved` (deferred indefinitely).
Update the status when a plan graduates to `BACKLOG.md` or ships.

| Plan | Status | VISION theme | Hard deps (blocked by) | Enables (blocks) | Soft / relates to |
|---|---|---|---|---|---|
| **normalized-schema-plan.md** | `building` · phases 1–2 shipped (`meta_*` contract live); residual phases outstanding | Detection & intel depth | — | operationalizing-intel (phase 1); http-honeypot (author into contract) | malware-catalog (download `meta` keys ↔ provenance) |
| **operationalizing-intel-plan.md** | `draft` · hard block cleared (schema phase 1 shipped); next slice: phase 1 (url/dl_host/HASSH into normalized schema) | Operationalizing the intel | normalized-schema (phase 1) | — | malware-catalog (campaign L2/L3 selectors); dashboard-overhaul (owns rendering ⇄); incident-response (alerting ⇄, egress/breakout); Trust & audit secrets (forcing function) |
| **dashboard-overhaul-plan.md** | `building` · Triage + Operate tiers shipped (JSON-validated; live verification pending); Hunt/deep-dives outstanding | Operationalizing the intel | normalized-schema (the `meta_*` contract) | — | operationalizing-intel (rendering ⇄ for pivot/replay/alert-state); alerting (P1 detection dashboard → Triage); malware-catalog (malware deep-dive) |
| **alerting-plan.md** | `building` · Phase 1 live (detector + `{job="detections"}` + Triage detection dashboard on log-stack); Phases 4–7 outstanding | Operationalizing the intel | — *(soft: normalized-schema for `meta_*`)* | — | operationalizing-intel (campaign-novelty needs correlation; digest sink); dashboard-overhaul (detection dashboard → Triage); malware-catalog (novelty registry / family); incident-response (security-model / egress gap) |
| **http-honeypot-plan.md** | `built` · phases 1–3 on `mysql-ssh`; :443 + dashboard outstanding | Detection & intel depth | — *(strongly: after normalized-schema)* | — | malware-catalog (feeds uploaded samples) |
| **malware-catalog/PLAN.md** | `building` · see own `PLAN.md` | Detection & intel depth (malware) | — *(mostly standalone)* | operationalizing-intel campaign features | http-honeypot (consumes its samples) |
| **canary-credentials-plan.md** | `proposed` · within-net replay = no-regret slice; external tokens build-at-trigger | Detection & intel depth (deception) | — *(soft: normalized-schema for pubkey match)* | — | alerting (deception-tripwire rule class ⇄); operationalizing-intel (campaign-grade replay ⇄); http-honeypot (`_BAIT` planting site ⇄); malware-catalog (registry table) |
| **high-interaction-pots-plan.md** | `proposed` · design-first, gated on containment bar + egress capture | Detection & intel depth (interaction depth) | — *(gated: Phase 1 threat model, Phase 2 egress capture)* | — | operationalizing-intel (feeds deep sessions for TTP §3a); alerting (egress capture → breakout rule); incident-response (breakout expected); aws-eks (isolation trade-off) |
| **multi-operator-plan.md** | `draft` · build-at-trigger (2nd operator joins) | Reach & multi-operator | — | incident-response (delivers the rotatable anchor) | aws-eks-migration-plan (per-provider break-glass) |
| **incident-response-plan.md** | `draft` · blocked on multi-operator | Trust & audit + Operational maturity | multi-operator (single rotatable anchor) | — | operationalizing-intel (alerting/self-healing); aws-eks (break-glass console) |
| **aws-eks-migration-plan.md** | `shelved` · "Maybe" (argues against itself) | Cloud portability | — | — | multi-operator (break-glass differs per provider). A "Maybe" — see plan's own recommendation against it on cost grounds. |
| **deployment-plan.md** | `building` · Phase 1 shipped (pattern in root `CLAUDE.md`); Phases 2–5 build-at-trigger | Operational maturity | — *(cross-cutting; every plan's changes ride it)* | reconfigure (Phase 2 graduated into a child plan) | incident-response (intentional push ⇄ recovery/self-healing); multi-operator (delivers live-config for operator-set); alerting (secret-push for Phase 2 tokens); secrets-management thread (gap 6 forcing function) |
| **reconfigure-plan.md** | `draft` · port composer + live host-config path, built as one effort | Operational maturity | — *(after deployment-plan Phase 1 pattern, already shipped)* | — | deployment-plan (implements Phase 2; Phase 4 gate consumes ⇄); multi-operator (live-config delivery for operator-set, gap 7); secrets-management (borders gap 6, kept separate); `!TESTING` (port composer = anchor for the offline tier-1/2 suite) |

## Recommended build order

Respecting the hard edges, the near-term path is:

1. **`normalized-schema-plan.md`** — ✅ **phases 1–2 shipped** (keystone done).
   Residual work: carry `protocol` onto every event + cowrie `client_fingerprint`/
   `client_version` (deferred Q5 spike); telnet re-scope. These are non-blocking
   for everything below except the Q5-gated panels.
2. **Active parallel tracks:**
   - **`dashboard-overhaul-plan.md`** — ✅ **Triage + Operate tiers shipped**
     (pending live verification). Next: Hunt tier (Credential intel + Download &
     infra intel on `meta_*`), coordinated with operationalizing for the campaign
     pivot and session replay. Q5-blocked panels (fingerprint, telnet view) wait on
     the schema spike.
   - **`operationalizing-intel-plan.md`** — hard block cleared. Next slice: phase 1
     (promote `url`/`dl_host`/HASSH into normalized schema per-honeypot).
   - **`alerting-plan.md`** — ✅ **Phase 1 live** (detector service + `{job="detections"}`
     + Triage detection dashboard on log-stack). Next: selector-novelty
     registry increment (Phase 4), then notification services (Phase 2).
   - **`http-honeypot-plan.md`** — ⚠️ shipped ahead of the schema keystone. Will
     need retrofitting once the normalized-schema residual work (Q5) touches
     `protocol` and fingerprinting.
3. **`malware-catalog/PLAN.md`** — independent; can advance anytime. Its Phase 1
   enrichment (family / IOCs / imphash) should land *before* operationalizing's
   campaign L2/L3, which consumes those selectors.
4. **`multi-operator-plan.md` → `incident-response-plan.md`** — gated by the
   multi-operator build trigger (a second operator actually joins). The anchor it
   delivers is a precondition for the incident-response rotation runbook.
5. **`aws-eks-migration-plan.md`** — conditional. Only if honey-net becomes a
   multi-region research platform; the plan itself argues against it for a
   small fleet.
6. **`canary-credentials-plan.md`** and **`high-interaction-pots-plan.md`** — newer
   Detection & intel depth threads, both `proposed`. Canary's within-net replay is a
   no-regret slice that can advance alongside alerting's selector-novelty work;
   high-interaction is design-first and gated on its containment bar + the shared
   honeypot-egress capture, so it trails until that lands.

## Cross-cutting threads (not single plans)

Some concerns recur across plans and have no dedicated plan file yet:

- **Secrets management** (Trust & audit theme) — first forced by outbound write
  credentials: alerting's notification-channel tokens (Telegram/Discord) and
  operationalizing-intel's publishing keys (ThreatFox / MalwareBazaar). reconfigure-plan
  deliberately excludes secret/`.env` push (gap 6) so a config push can't clobber a
  secret — filling that boundary is this thread's to own. May graduate to its own plan
  when that work starts.
- **Testing** (Operational maturity theme) — now has a strategy doc, `docs/!TESTING.md`:
  the test tiers (offline unit/contract → live smoke/operational → integration),
  coverage map, and conventions. deployment-plan Phase 4 (verification gate) and Phase 5
  (CI) execute it; reconfigure-plan's port composer is the anchor for the first offline
  tier. A cross-cutting strategy like `!DESIGN` / `!DEPENDENCIES`, not a plan node.
- **Self-describing package model** (`docs/!DESIGN.md`) — the invariant that
  normalized-schema, http-honeypot, malware-catalog, and now reconfigure (declarative
  `package.toml`) all build on; new pots add no control-plane changes.
- **Alerting** — **now its own plan**, `docs/alerting-plan.md` (graduated out of
  operationalizing-intel). Build it once there; incident-response and the dashboard
  Triage tier consume it.
