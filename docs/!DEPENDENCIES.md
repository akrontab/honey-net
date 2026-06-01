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
  uses     → malware-catalog          (soft: campaign selectors — family/IOCs/imphash)
  pairs    ↔ dashboard-overhaul       (soft: this owns actions, that owns rendering — pivot/replay/alert-state seam)
  pairs    ↔ incident-response        (soft: alerting, egress/breakout)

dashboard-overhaul-plan       (operationalizing theme — the visualization surface)
  requires → normalized-schema        (hard: consumes the meta_* contract)
  pairs    ↔ operationalizing-intel   (soft: owns rendering for its pivot/replay/alert-state)
  uses     → malware-catalog          (soft: malware deep-dive)

http-honeypot-plan
  after    → normalized-schema        (recommended: built into the generalized contract)
  feeds    → malware-catalog          (soft: supplies uploaded samples)

malware-catalog/PLAN          (mostly standalone — depends on nothing)
  enables  → operationalizing-intel   (soft: campaign L2/L3 selectors)
  pairs    ↔ http-honeypot            (soft: consumes its samples)

multi-operator-plan           (depends on nothing)
  enables  → incident-response        (hard: delivers the single rotatable anchor)
  pairs    ↔ aws-eks-migration        (soft: per-provider break-glass)

incident-response-plan
  requires → multi-operator           (hard: the single rotatable anchor)
  pairs    ↔ operationalizing-intel   (soft: alerting / self-healing)
  pairs    ↔ aws-eks-migration        (soft: break-glass console differs per provider)

aws-eks-migration             (standalone "Maybe" — depends on nothing)
  pairs    ↔ multi-operator           (soft: break-glass)
```

## Dependency table

**Status** values: `draft` (plan only) · `building` (partially shipped) · `built`
(graduated and shipped; residual items noted) · `shelved` (deferred indefinitely).
Update the status when a plan graduates to `BACKLOG.md` or ships.

| Plan | Status | VISION theme | Hard deps (blocked by) | Enables (blocks) | Soft / relates to |
|---|---|---|---|---|---|
| **normalized-schema-plan.md** | `draft` · build-next (keystone) | Detection & intel depth | — | operationalizing-intel (phase 1); http-honeypot (author into contract) | malware-catalog (download `meta` keys ↔ provenance) |
| **operationalizing-intel-plan.md** | `draft` · blocked on normalized-schema | Operationalizing the intel | normalized-schema (phase 1) | — | malware-catalog (campaign L2/L3 selectors); dashboard-overhaul (owns rendering ⇄); incident-response (alerting ⇄, egress/breakout); Trust & audit secrets (forcing function) |
| **dashboard-overhaul-plan.md** | `draft` · contract ready, build-next candidate | Operationalizing the intel | normalized-schema (the `meta_*` contract) | — | operationalizing-intel (rendering ⇄ for pivot/replay/alert-state); malware-catalog (malware deep-dive) |
| **http-honeypot-plan.md** | `built` · phases 1–3 on `mysql-ssh`; :443 + dashboard outstanding | Detection & intel depth | — *(strongly: after normalized-schema)* | — | malware-catalog (feeds uploaded samples) |
| **malware-catalog/PLAN.md** | `building` · see own `PLAN.md` | Detection & intel depth (malware) | — *(mostly standalone)* | operationalizing-intel campaign features | http-honeypot (consumes its samples) |
| **multi-operator-plan.md** | `draft` · build-at-trigger (2nd operator joins) | Reach & multi-operator | — | incident-response (delivers the rotatable anchor) | aws-eks-migration (per-provider break-glass) |
| **incident-response-plan.md** | `draft` · blocked on multi-operator | Trust & audit + Operational maturity | multi-operator (single rotatable anchor) | — | operationalizing-intel (alerting/self-healing); aws-eks (break-glass console) |
| **aws-eks-migration.md** | `shelved` · "Maybe" (argues against itself) | Cloud portability | — | — | multi-operator (break-glass differs per provider). A "Maybe" — see plan's own recommendation against it on cost grounds. |

## Recommended build order

Respecting the hard edges, the near-term path is:

1. **`normalized-schema-plan.md`** — the keystone. Unblocks operationalizing
   phase 1 *and* cleanly precedes the HTTP pot. Nothing else in the intel cluster
   should start first.
2. **In parallel after (1):**
   - **`operationalizing-intel-plan.md`** — phase 1 (the schema slice) onward.
   - **`dashboard-overhaul-plan.md`** — the `meta_*` contract has landed (schema
     phases 1–2), so this is unblocked and a strong build-next candidate: the old
     dashboards are being replaced and should be rebuilt onto the contract rather
     than retrofitted. Its Hunt-tier pivot/replay coordinate with operationalizing.
   - **`http-honeypot-plan.md`** — ⚠️ **already shipped ahead of (1)** (built on
     `mysql-ssh`). It was meant to be authored *into* the generalized contract;
     since normalized-schema landed after it, the HTTP pot will need retrofitting
     when (1) is done — exactly the "hand-coded Cowrie-shaped" retrofit the keystone
     was meant to avoid. Factor this into the normalized-schema work.
3. **`malware-catalog/PLAN.md`** — independent; can advance anytime. Its Phase 1
   enrichment (family / IOCs / imphash) should land *before* operationalizing's
   campaign L2/L3, which consumes those selectors.
4. **`multi-operator-plan.md` → `incident-response-plan.md`** — gated by the
   multi-operator build trigger (a second operator actually joins). The anchor it
   delivers is a precondition for the incident-response rotation runbook.
5. **`aws-eks-migration.md`** — conditional. Only if honey-net becomes a
   multi-region research platform; the plan itself argues against it for a
   small fleet.

## Cross-cutting threads (not single plans)

Some concerns recur across plans and have no dedicated plan file yet:

- **Secrets management** (Trust & audit theme) — first forced by
  operationalizing-intel's outbound write credentials (alert webhook, ThreatFox /
  MalwareBazaar keys). May graduate to its own plan when that work starts.
- **Self-describing package model** (`docs/!DESIGN.md`) — the invariant that
  normalized-schema, http-honeypot, and malware-catalog all build on; new pots
  add no control-plane changes.
- **Alerting** — surfaces as an open question in incident-response *and* as a core
  direction in operationalizing-intel; build it once, in operationalizing, and let
  incident-response consume it.
