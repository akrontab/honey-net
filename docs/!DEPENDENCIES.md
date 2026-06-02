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
  pairs    ↔ malware-catalog          (soft: download `meta` ↔ provenance)

operationalizing-intel-plan
  requires → normalized-schema        (hard: phase 1 prerequisite)
  enables  → alerting                 (soft: campaign correlation defines campaign-novelty rule)
  uses     → malware-catalog          (soft: campaign selectors — family/IOCs/imphash)
  pairs    ↔ dashboard-overhaul       (soft: this owns actions, that owns rendering — pivot/replay/alert-state seam)
  pairs    ↔ incident-response        (soft: alerting, egress/breakout)

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

http-honeypot-plan
  after    → normalized-schema        (recommended: built into the generalized contract)
  feeds    → malware-catalog          (soft: supplies uploaded samples)

malware-catalog/PLAN          (mostly standalone — depends on nothing)
  enables  → operationalizing-intel   (soft: campaign L2/L3 selectors)
  pairs    ↔ http-honeypot            (soft: consumes its samples)

multi-operator-plan           (depends on nothing)
  enables  → incident-response        (hard: delivers the single rotatable anchor)
  pairs    ↔ aws-eks-migration-plan   (soft: per-provider break-glass)

incident-response-plan
  requires → multi-operator           (hard: the single rotatable anchor)
  pairs    ↔ operationalizing-intel   (soft: alerting / self-healing)
  pairs    ↔ aws-eks-migration-plan   (soft: break-glass console differs per provider)

aws-eks-migration-plan        (standalone "Maybe" — depends on nothing)
  pairs    ↔ multi-operator           (soft: break-glass)
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
| **multi-operator-plan.md** | `draft` · build-at-trigger (2nd operator joins) | Reach & multi-operator | — | incident-response (delivers the rotatable anchor) | aws-eks-migration-plan (per-provider break-glass) |
| **incident-response-plan.md** | `draft` · blocked on multi-operator | Trust & audit + Operational maturity | multi-operator (single rotatable anchor) | — | operationalizing-intel (alerting/self-healing); aws-eks (break-glass console) |
| **aws-eks-migration-plan.md** | `shelved` · "Maybe" (argues against itself) | Cloud portability | — | — | multi-operator (break-glass differs per provider). A "Maybe" — see plan's own recommendation against it on cost grounds. |

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
4. **`malware-catalog/PLAN.md`** — independent; can advance anytime. Its Phase 1
   enrichment (family / IOCs / imphash) should land *before* operationalizing's
   campaign L2/L3, which consumes those selectors.
5. **`multi-operator-plan.md` → `incident-response-plan.md`** — gated by the
   multi-operator build trigger (a second operator actually joins). The anchor it
   delivers is a precondition for the incident-response rotation runbook.
6. **`aws-eks-migration-plan.md`** — conditional. Only if honey-net becomes a
   multi-region research platform; the plan itself argues against it for a
   small fleet.

## Cross-cutting threads (not single plans)

Some concerns recur across plans and have no dedicated plan file yet:

- **Secrets management** (Trust & audit theme) — first forced by outbound write
  credentials: alerting's notification-channel tokens (Telegram/Discord) and
  operationalizing-intel's publishing keys (ThreatFox / MalwareBazaar). May graduate
  to its own plan when that work starts.
- **Self-describing package model** (`docs/!DESIGN.md`) — the invariant that
  normalized-schema, http-honeypot, and malware-catalog all build on; new pots
  add no control-plane changes.
- **Alerting** — **now its own plan**, `docs/alerting-plan.md` (graduated out of
  operationalizing-intel). Build it once there; incident-response and the dashboard
  Triage tier consume it.
