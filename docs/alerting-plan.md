# Alerting — Plan

Graduation of the alerting thread out of `docs/operationalizing-intel-plan.md`
(the **Operationalizing the intel** theme): turn high-signal detections — novel
attacks, security-model violations, and (later) novel campaigns — into something
that reaches a human. Kept as its own atomic plan so it sequences independently of
the heavier campaign-analytics, digest, and publishing work that stays in the
parent.

This is a *plan*, not buildable tasks.

## Boundary — what this plan owns

Owns the **alerting concern end to end**: the detection rules, the detection-event
contract, the proof-of-concept detection dashboard, and the notification services.
`operationalizing-intel-plan.md` keeps the campaign **analytics ladder**
(correlation L0–L3), the **digest** job, **outbound publishing**, and the
**provenance join**, and references this plan for anything that alerts.

**Supersedes** operationalizing-intel §1's "notification = Grafana unified alerting
+ one contact point." Notification here is **custom services**
(Telegram / Discord / callout / …) following the repo's worker/service idiom — more
flexible per-channel and free of Grafana's reporting/enterprise limits.

## Phased approach — prove, then act

Deliberately two independently-shippable phases:

- **Phase 1 — detection + visualization (the PoC).** Define the rules, emit
  detections, and show "what fired in the last X" on a dashboard. **No
  notifications.** The dashboard is the feedback loop that proves rules fire on real
  signal without drowning in false positives. Tune rules here, cheaply, before
  anything pages.
- **Phase 2 — notification services.** Once a rule is *trusted*, one or many
  services consume its detections and deliver to a channel. Pluggable: a channel is
  a new service, not a rewrite.

The two phases meet at one seam — **the detection-event contract** (below). Phase 1
produces it; Phase 2 consumes it. Get the contract right and channels are additive.

## The detection-event contract (the seam)

Rules emit a normalized **detection event** to a dedicated stream
`{job="detections"}` in Loki:

```json
{
  "timestamp": "...",
  "rule_id":   "real-ssh-auth-success",
  "severity":  "page|notice|digest",
  "category":  "security-model|novelty|threshold|campaign",
  "entity":    "1.2.3.4",        // the notable thing (IP, dl_host, sha256, family, sensor)
  "summary":   "successful auth on :65022 from a non-operator IP",
  "context":   { /* rule-specific: src_ip, honeypot, host, sample_sha256, ... */ }
}
```

- **Severity is assigned at detection time** and is what Phase 2 routes on (`page` →
  immediate channel; `notice` → channel, batchable; `digest` → handed to
  operationalizing's digest as the non-urgent catch-basin).
- The dashboard (P1) and the notification services (P2) are both **source-agnostic
  consumers** of this stream — neither re-implements rule logic.

## Detection mechanism

A small **detector service** (the repo's polling-worker idiom — cf. the catalog
workers) runs on **log-stack** (Loki-local, Tailscale to the catalog). It
periodically evaluates the rule set against `{job="events"}`, `{job="auth"}` /
`syslog`, and the catalog API, and writes detection events to `{job="detections"}`.
One place for rule logic; uniform handling of both log-pattern and catalog/stateful
rules.

*Considered alternative:* provisioned Grafana alert rules — cheaper for pure-LogQL
conditions but can't express catalog joins or first-seen novelty, and re-centralizes
on Grafana. See open question 1.

## The rules — strongest / cheapest first

| # | Rule class | Examples | Cost today | Phase |
|---|---|---|---|---|
| 1 | **Security-model violation** (rare by construction → highest signal, lowest noise) | success auth on real SSH :65022 from a non-operator IP; root login on a honeypot host; sensor gone dark (no events in N min) | `{job="auth"}`/`syslog` + `{job="events"}` — **free** | 1 |
| 2 | **Sample novelty** | new SHA-256 ever seen | catalog `new_sample` audit — **free** | 1 |
| 3 | **Threshold / volume** (noisy — needs `for:` + dedup or it storms) | scan spikes, credential bursts | `{job="events"}` — cheap | 1 (a couple, to exercise dedup) |
| 4 | **Selector novelty** (self-limiting; the high-value campaign signal) | new `dl_host` (infra), new family (payload), new HASSH (tooling) | needs a **first-seen registry**; HASSH **blocked on schema Q5** | 1 increment |
| 5 | **Campaign novelty** | a new cluster / conjunction of selectors appears | needs correlation (operationalizing L1/L2) | **build-at-trigger** |

Favor **violations** (1) and **novelty** (2, 4) over **thresholds** (3): on
constantly-attacked honeypots raw volume *is* the baseline, so threshold rules are
noisy while violation/novelty rules are rare by construction and self-limiting.

### Novelty state — first-seen registry

Novelty rules (4) must remember what's been seen so each entity fires **once**.
Lean: **extend the catalog as the registry** — it is already the first-seen source
of truth for samples (SHA-256 dedup). Add a small
`first_seen(selector_type, value, first_seen_at, context)` table + a `novel_<type>`
audit event on first insert; the detector reads/writes it. This survives Loki's
30-day retention (a Loki-only `count==1` approximation does not — it re-fires after
entities age out). See open question 2.

### Capture gap — honeypot egress

The single highest-signal breakout rule — "a box that should only *receive* traffic
is now *initiating* it" — likely isn't capturable today (we ship `auth.log` /
`syslog`, not egress / conntrack). Noted as a dependency, shared with
`incident-response-plan.md`; the rule lands when egress logging does.

## Notification services (Phase 2)

Per channel, a small service consuming `{job="detections"}`, routed by `severity`:

- **dispatcher** — reads detections, applies the notification policy
  (grouping / throttle / silence / severity → channel), fans out to channel
  services.
- **channel services** — Telegram, Discord, webhook/callout, … each owns its API +
  secret. Adding a channel = a new service + a route; **no change to detection.**

Runs on **log-stack**. Channel tokens are the first **outbound-write secrets** here
(Telegram bot token, Discord webhook URL) — document each as a secret from day one
(`.env` for now), a forcing function for the **Trust & audit** secrets work. New
**egress** (log-stack → Telegram/Discord APIs) to UFW-allow and document; all on
hardened infra, never the honeypots.

## Relationship to other plans

- **`operationalizing-intel-plan.md`** — alerting graduates *out* of it; it keeps
  campaign analytics (L0–L3), the digest, publishing, and provenance.
  **Campaign-novelty detection (rule 5) depends on its correlation** to define a
  "campaign," so that rule is build-at-trigger here. Its §1/§2 notification design is
  superseded by the custom-services approach above; the digest remains its artifact
  and is the `digest`-severity sink.
- **`normalized-schema-plan.md`** — rules read `{job="events"}` + `meta_*`.
  **HASSH/fingerprint novelty (rule 4) is blocked on its deferred Q5** (fingerprint
  not yet in the normalized stream).
- **`dashboard-overhaul-plan.md`** — the Phase 1 detection dashboard is kept here to
  stay atomic, and **folds into that plan's Triage tier** (live alert state) once
  Phase 2 notifications own the "tell me" job.
- **`malware-catalog/PLAN.md`** — `new_sample` is free today; the novelty registry
  extends the catalog DB; family novelty reads `consensus_family`.
- **`incident-response-plan.md`** — the security-model-violation rules and the
  honeypot-egress capture gap overlap with breakout detection there.

## Phases (graduation order)

1. **Detection-event contract** — define the `{job="detections"}` schema + severity
   tiers.
2. **Detector service + free rules** — service on log-stack emitting detections for
   rule classes 1–3.
3. **Detection dashboard** — "what fired in the last X," by severity / category /
   entity. *Phase 1 PoC complete here.*
4. **Selector-novelty increment** — first-seen registry in the catalog +
   `novel_<type>`; rule class 4 (sans HASSH until schema Q5).
5. **Notification dispatcher + first channel** — dispatcher + one channel service
   (e.g. Telegram), severity-routed.
6. **Additional channels** — Discord / webhook / callout as added services.
7. **(Build-at-trigger) Campaign novelty** — rule class 5, after operationalizing
   correlation exists.

## Open questions (resolve before BACKLOG)

1. **Detector mechanism** — custom detector service (above) vs. provisioned Grafana
   alert rules vs. hybrid. *Lean: custom service — the only one that does catalog
   joins + first-seen novelty and stays Grafana-independent for notification.*
2. **Novelty registry home** — extend the catalog DB (lean) vs. a detector-owned
   store. *Lean: catalog — already the first-seen source of truth; keeps "what we've
   seen" in one place.*
3. **Detections → dispatcher transport** — services tail `{job="detections"}` from
   Loki vs. the detector POSTs the dispatcher directly. *Lean: Loki tail — one
   stream, dashboard and dispatcher share it, decoupled.*
4. **Severity policy** — fixed per-rule severity vs. a routing layer that can re-tier
   without editing rules. *Lean: severity on the detection event + a thin routing
   table in the dispatcher.*
5. **Operator-IP allowlist** — the "non-operator IP" in rule 1 needs a source of
   truth (Tailscale ACL / a config list). *Lean: a small config alongside the
   operator data in `honey-net.json`.*

## Graduation to BACKLOG

Phase 1 (steps 1–3) **live** on log-stack. Steps 4–7 graduate as their triggers / deps clear.

- [x] Detection-event contract (`{job="detections"}` schema + severity tiers) — documented in `alerting/CLAUDE.md`
- [x] Detector service on log-stack emitting rule classes 1–3 — `alerting/deploy/detector/detector.py`
- [x] Detection dashboard (last-X, by severity / category / entity) — `log-stack/deploy/grafana/provisioning/dashboards/Triage/detections.json` (uid `triage-detections`)
- [ ] First-seen registry in the catalog + `novel_<type>`; selector-novelty rules (rule 4, ex-HASSH)
- [ ] Notification dispatcher + first channel (Telegram), severity-routed
- [ ] Additional channel services (Discord / webhook / callout)
- [ ] (Trigger) campaign-novelty rule once operationalizing correlation lands
- [ ] (Blocked on schema Q5) HASSH / fingerprint novelty
