# Canary Credentials — Plan

New thread under the **Detection & intel depth** theme in `docs/!VISION.md`
("extract more signal from what we capture"), with its detection output flowing
through `docs/alerting-plan.md`. The honey-net already serves bait; this plan
turns that bait into **tracked honeytokens** — uniquely-identifiable planted
secrets whose *reuse* is a detection in its own right.

The question it answers is the operator's: *"did anyone take the credentials we
left lying around, and where did they try them?"* A `login` brute-force tells you
someone is guessing. A **canary replay** tells you someone read your fake `.env`,
believed it, and is now acting on it — a categorically higher-signal event, and
one only a deception sensor can produce.

This is a *plan*, not buildable tasks. The within-net detection (below) is a
cheap, no-regret slice; external canary tokens are explicitly **build-at-trigger**.

> **Status: `proposed`.** No code yet — but the two structural questions
> (registry home Q2, uniqueness granularity Q1) are now **resolved** (see §1a +
> Open questions), so the no-regret slice (Phases 1–2) is BACKLOG-ready.

## Scope & timing — plan, not a build order

**Build triggers:**

- **Now / no-regret** — formalize the scattered static bait into a **token
  registry** and add a **within-net replay** rule to the existing detector. Cheap
  (reads core `username`/`password` already in `{job="events"}`), and the
  cross-pot replay case is among the highest-signal detections we can field.
- **When a second deployment exists** — make tokens **unique per sensor /
  deployment** so a hit attributes the leak to a specific pot.
- **Build-at-trigger** — **external** canary tokens (a hit observable *outside*
  the honeynet). Real "used elsewhere," but adds third-party callbacks, outbound
  secrets, and an abuse surface — defer until the within-net signal proves the
  idea earns the infra.

## Current state (what we're building on)

| Capability | Today |
|---|---|
| Planted secrets | **static strings**, hardcoded in the HTTP pot's `_BAIT` (`/.env` → `DB_PASSWORD=S3cr3t-Pa55!`, `AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE`; `/.git/config`; `/.aws/credentials`) |
| Planted SSH keys | Cowrie captures attacker-*planted* keys, but we don't *seed* identifiable keys for reuse-tracking |
| Token inventory | **none** — no canonical list of "what we planted and where" |
| Uniqueness | **none** — the `.env` secrets are identical across every deployment, so a hit can't be attributed to a sensor |
| Reuse detection | **none** — nothing watches for a planted value coming back as a login |
| Detection plumbing | **exists** — `{job="detections"}` + the detector service on log-stack (`alerting-plan.md`) is the natural home for a replay rule |

## Design direction

### 1. The token registry — one source of truth for "what's a canary"

Planted values today live inline in pot code. Centralize them into a **registry**
the detector can read: each entry is `{token_id, value, kind, planted_in,
deployment}`. The honeypot still *serves* the value (it's bait, served from an
untrusted box on purpose); the registry of *which values are canaries* lives on
hardened infra so a compromised pot can't read the full set and avoid them.

The HTTP `_BAIT` map becomes the **first producer** — its secrets are drawn from
(or registered into) the registry rather than being magic literals.

### 1a. Token lifecycle — generated at deploy, registered out-of-band (resolves Q1 + Q2)

Planting and detection must stay on **opposite sides of the trust boundary**:

```
CONTROL PLANE (trusted, at provision / redeploy)
  generate per-deployment token values (structurally-valid fakes)
    ├─► bake into the pot's config  (HTTP _BAIT templated, shipped by redeploy — NOT .env)
    └─► INSERT {token_id, value, kind, planted_in, deployment, planted_at}
          into the catalog `canaries` table
                                   │
   HONEYPOT (untrusted)           │            DETECTOR (trusted, on log-stack)
     serves only its own value;   └──────────►   queries `canaries`, matches the
     never reads the registry                     value-set against {job="events"}
                                                  username / password / pubkey
```

The rule that makes this safe and **resolves Q2 (registry home = the catalog
`canaries` table)**: a honeypot knows only the token it serves, never the
registry — so a compromised pot can't enumerate the canary set to avoid tripping
it. Generation and registration are **control-plane** actions, so adding or
rotating a token is a deploy, not a live-pot mutation. The `canaries` table is
**mutable** (tokens retire and rotate) and sits alongside the first-seen novelty
registry the detector already reads (`alerting-plan.md`), distinct from the
catalog's insert-only *sample* records. Baking values into pot **config** (not
`.env`) keeps them on the `redeploy` live path rather than the no-live-path `.env`
seam (`CLAUDE.md`).

**Q1 (uniqueness granularity) is resolved to per-deployment** — enough to
attribute a hit to a sensor without a token-per-request management burden. But
uniqueness only earns its keep at the **second** deployment, so the generation
machinery is **Phase 4**: Phases 1–2 simply register the *existing static* `_BAIT`
values for the one live deployment and wire up replay detection against them.

### 2. Token taxonomy — each kind has its own reuse detector

| Token kind | Planted as | Reuse looks like |
|---|---|---|
| DB / form credentials | `.env` `DB_USERNAME`/`DB_PASSWORD`, fake admin creds | a `login`/`query` event whose `username`/`password` matches a token |
| Cloud access key | `.env` / `.aws/credentials` AWS key pair | within-net: submitted as creds; **external**: used against a monitored cloud account (CloudTrail) |
| API token / webhook URL | `.env` secrets, config files | within-net: replayed as auth; **external**: a callback to a unique URL we control |
| SSH key | seeded into a pot filesystem | the public key reappears as an attacker auth attempt (`auth_method=pubkey`) |
| Tracked URL / DNS token | a unique hostname in a bait file | a DNS lookup / fetch of that unique name (out-of-band) |

The first three are detectable **within the net today**; the last two are the
**external** tier.

### 3. Detection tiers — where "elsewhere" actually is

```
Tier 1 — WITHIN-NET REPLAY  (no-regret, build now)
  attacker GETs /.env on the HTTP pot  ──►  later submits acme_app / S3cr3t-Pa55!
  as a login to the *MySQL* pot.  Detector matches the submitted creds against the
  registry → emits a `canary-replay` detection.  The cross-pot case
  (planted-in-HTTP, replayed-against-MySQL) is the headline signal.

Tier 2 — PROVENANCE LINKAGE  (cheap follow-on)
  join the replay back to the bait-fetch: same src_ip / session that read the
  bait earlier?  time-to-replay?  → confirms attribution + measures how convincing
  the bait was.

Tier 3 — EXTERNAL CANARY TOKENS  (build-at-trigger; the literal "used elsewhere")
  seed tokens whose *use* is observable outside the honeynet — an AWS key wired to
  a CloudTrail alert, a unique URL/DNS token (canarytokens.org model).  A hit proves
  the credential left our net and was used in the wild.
```

Detection runs in the **existing detector service** (`alerting-plan.md`): a new
rule class — call it **deception tripwire** — reads `{job="events"}` and matches
`username`/`password` (and pubkey fingerprint) against the registry. It rides the
same `{job="detections"}` contract and severity routing; a canary replay is
**page-worthy**, not digest.

### 4. Uniqueness vs. realism — the core design tension

To attribute a hit ("which sensor leaked this?") tokens must be **unique per
planting location, ideally per deployment**. But a credential that's obviously
unique is also obviously a canary. The resolution is the canarytokens approach:
generate values that are *structurally valid* for their kind (an AWS key with a
real key-id format, a plausible password) while carrying a registry-side
identifier — uniqueness lives in the lookup table, not in a visibly-weird value.

## Phases

1. **Token registry + inventory.** Define the registry schema and home (Q2);
   migrate HTTP `_BAIT` to draw planted secrets from it. No detection yet — just
   "we now know what we planted, where."
2. **Within-net replay detection (Tier 1).** `deception-tripwire` rule in the
   detector: match `{job="events"}` creds against the registry → `canary-replay`
   detection (`page` severity). Cross-pot replay is the headline test case.
3. **Provenance linkage (Tier 2).** Correlate a replay to the originating
   bait-fetch (src_ip/session/time); annotate the detection with "bait read N
   minutes earlier from pot X."
4. **Per-deployment uniqueness.** Tokens unique per sensor so a hit attributes the
   leak; folds into the registry once a second deployment exists.
5. **(Build-at-trigger) External canary tokens (Tier 3).** AWS-key / DNS / URL
   canaries with out-of-band callback; the first time "used elsewhere" becomes
   literally true.

## Open questions (resolve before BACKLOG)

1. **Uniqueness granularity** — ✅ **Resolved: per-deployment** (see §1a); deferred
   to Phase 4, since it only matters at the second deployment.
2. **Registry home** — ✅ **Resolved: catalog `canaries` table** (see §1a),
   control-plane-written and detector-read; pots never query it.
3. **Token realism** — how structurally-valid must a fake AWS key / password be to
   be believed, and does generating valid-looking tokens need a helper?
4. **External canary provider (Tier 3)** — self-hosted callback vs.
   canarytokens.org vs. cloud-native (CloudTrail on a burner AWS account)?
5. **Scope of "credentials"** — creds + cloud keys only, or also seeded SSH keys
   (Cowrie) and tracked URLs/documents from the start?

## Graduation to BACKLOG

With Q1/Q2 resolved, the no-regret slice can graduate now; Tier 2 follows, Tier 3
stays gated on its build trigger.

- [ ] Phase 1 — `canaries` table in the catalog (`token_id, value, kind, planted_in, deployment, planted_at`); register the existing static HTTP `_BAIT` secrets; template `_BAIT` from config
- [ ] Phase 2 — `deception-tripwire` rule in the detector: match `{job="events"}` `username`/`password` against the registry → `canary-replay` detection (`page` severity); cross-pot replay is the acceptance test
- [ ] Phase 3 — provenance linkage: annotate a replay with the originating bait-fetch (src_ip/session/time)
- [ ] (Trigger: 2nd deployment) Phase 4 — per-deployment token generation + uniqueness
- [ ] (Trigger: external signal wanted) Phase 5 — external canary tokens (AWS-key / DNS / URL, out-of-band callback)

Open questions still to settle before Phase 3+: token realism (Q3), external
provider (Q4), and credential scope beyond creds/keys (Q5).

## Relationship to other plans

- **`alerting-plan.md`** — the canary-replay detector is a **new rule class**
  ("deception tripwire") on its `{job="detections"}` contract; reuses the detector
  service, severity routing, and notification channels wholesale.
- **`operationalizing-intel-plan.md`** — a canary replay is a campaign-grade
  signal; the provenance linkage (Tier 2) is the same bait-fetch → replay join
  spirit as its catalog provenance join.
- **`normalized-schema-plan.md`** — Tier 1 reads only core `username`/`password`
  (already present); pubkey-fingerprint matching is **blocked on its deferred
  fingerprint promotion (Q5)**.
- **HTTP pot (`honey-pots/http/`)** — `_BAIT` is the first planting site and the
  first registry producer.
- **`incident-response-plan.md` / Trust & audit theme** — Tier 3 introduces
  outbound callbacks and external secrets; same egress/secret discipline as the
  intel plans' publishing work.
