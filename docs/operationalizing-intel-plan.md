# Operationalizing the Intel — Plan

Graduation of the **Operationalizing the intel** theme in `docs/!VISION.md`:
close the loop from capture to action — alerting on high-signal events and novel
indicators, scheduled digests, attacker session replay, and feeding indicators
back out to the community feeds we already pull from. Sits on the normalized
`{job="events"}` stream and the Grafana/Loki stack (`log-stack/`); outbound
sharing pairs with the export work under **Detection & intel depth**.

This is a *plan*, not buildable tasks. One prerequisite (schema promotion, below)
is a no-regret move that unblocks almost everything else; the heavier analytics
(campaign correlation, IP-novelty, outbound publishing) are explicitly
**build-at-trigger** and must not be built ahead of real need.

**Two concerns have graduated into their own atomic plans** — this plan is now the
campaign-analytics + publishing core:

- **Alerting** → `docs/alerting-plan.md`. Detection rules (novel attacks /
  security-model violations / novel campaigns), the detection dashboard, and
  **custom notification services** (Telegram/Discord/callout — superseding §1's
  "notification = Grafana unified alerting + one contact point" below). The **digest**
  stays here and is the `digest`-severity sink for that plan's routing.
- **Rendering** → `docs/dashboard-overhaul-plan.md`. Everything that draws on a
  screen — the campaign **pivot dashboard** (L1), **event-timeline session replay**,
  the **sensor-dark** surface — is owned and built there (Hunt/Operate tiers).

This plan keeps: the campaign maturity ladder (L0–L3 correlation), the digest job,
outbound publishing, and the catalog provenance join. The §1–§2 alerting design
below is **retained as background** but is superseded by `alerting-plan.md` on the
notification path; read it for the detection-source reasoning, not the Grafana
notification mechanism.

## Scope & timing — plan, not a build order

The honeypots already *collect* the signal. What's missing is the step from
collection to **action** (a notification, a digest, a shared indicator) and from
isolated selectors to **named campaigns**. The trap here is building a clustering
engine before we know what separates campaigns *in our own data* — so the plan
deliberately front-loads cheap instrumentation and defers automation.

**Build triggers:**

- **Now / no-regret** — promote the read-time-extracted selectors
  (`url`/`dl_host`/`dl_filename`, client fingerprints) into the normalized event
  schema. Serves alerting *and* campaign-learning at once; everything downstream
  depends on it.
- **When attack volume justifies it** — threshold alerting + a manual pivot
  dashboard (the instrument that *teaches* us the clustering rules).
- **After the pivot dashboard has taught the rules** — the durable
  session-summary store and any automated campaign correlator. Not before.
- **When a second consumer of the intel exists** (a block-list, a sharing
  partner, an on-call human) — outbound feed publishing and paging.

## Current state (what we're building on)

| Capability | Today |
|---|---|
| Normalized stream | `{job="events"}` — `connect`/`login`/`command`/`query`/`download`/`session_end`, schema in `honey-pots/CLAUDE.md` |
| Campaign selectors | **collected, not joined** — `dl_host`/`dl_filename` regex'd *at dashboard read-time*; HASSH / client banner / pubkey fingerprint live only in raw `{job="cowrie"}` |
| Sample novelty | **free** — catalog dedupes by SHA-256; `SampleService.upload` already emits a `new_sample` vs `duplicate` audit event (`services/samples.py`) |
| Sample provenance | **partially captured** — `sources` table stores `(sha256, src_ip, url, timestamp)`; `session_id` and `honeypot` are **dropped** at `add_source()` (see gap below) |
| Alerting | none — Grafana stack present, no alert rules, no contact points |
| Digests | none |
| Session replay | partial — `session-analysis` / `attacker-drilldown` dashboards exist; no session-keyed transcript or TTY replay |
| Outbound sharing | none — we pull from abuse.ch / MalwareBazaar (`intel-fetcher`), contribute nothing back |

## Design direction

### 1. Alerting: detection is distributed, notification is centralized

The two alerting modes are not two features — they are two **detection sources**
feeding one **notification path**:

```
DETECTION (stateful where state already exists)
  ├─ catalog → `new_sample` audit event on novel SHA-256        [free today]
  ├─ honeypot host → auth.log / syslog already shipped          [free today]
  ├─ events stream → {job="events"} normalized                  [free today]
  └─ (deferred) novelty on tight selectors → new dl_host / HASSH / family
                         │
                         ▼
NOTIFICATION (centralized)
  └─ Grafana unified alerting
       ├─ rules provisioned as YAML under provisioning/alerting/ (mirrors dashboards)
       ├─ notification policy: grouping / throttle / silence / severity routing
       └─ contact point → one outbound secret
```

Route **even catalog-detected novelty** back through Grafana rather than POSTing
a webhook from the catalog: one egress point, one secret, one place for
grouping/silencing/severity. Sources emit structured *facts*; Grafana owns
who-gets-told-how-loud.

**Threshold rules** are noisy on constantly-attacked honeypots — raw activity
*is* the baseline. Favor **"violates the security model"** rules, which are rare
by construction:

- successful auth on the **real** SSH port (`{job="auth"}`) from a non-operator IP
- **root login on a honeypot host itself** → possible breakout
- a honeypot **initiating outbound** traffic → exfil/C2 (capture gap — see below)
- a sensor **going dark** (no events from honeypot X in N min; `sensor-health`)

Volume/rate rules (scan spikes, credential bursts) are doable but need a `for:`
duration + notification-policy grouping or they storm.

**Novelty rules** are the good primitive — **self-limiting** (each fires once per
genuinely-new entity). The right novelty keys are **not "new IP"** (noise) but
the *tight* campaign selectors: **new sample** (free), **new `dl_host`**, **new
HASSH**, **new malware family** — new *infrastructure / tooling / payload* is
high-signal. This is the same set as the campaign selectors below, which is the
argument for doing schema promotion first.

### 2. Alerting and digests are one severity spectrum

Every rule gets a severity at routing time:

- **page-worthy** → contact point now (security-model violation, novel sample)
- **digest-worthy** → suppressed from real-time, **rolls into the scheduled digest**
- **dashboard-only** → no notification

So the digest is the **catch-basin for everything that's signal but not urgent**,
defined by the *same* routing layer. Build the routing once, get both ends. The
digest is a render-and-send job (Grafana reporting is Enterprise-only) on the
log-stack host — it has Loki local and Tailscale reach to the catalog API.

### 3. Campaigns: a maturity ladder, not an engine

A campaign is a **cluster of observations sharing selectors that wouldn't
co-occur by chance** — usually a *conjunction* (e.g. "HASSH X **AND** fetches
`arm7`/`mips` from host-set Y **AND** drops family Z, across these IPs"). The
selectors, strongest first, and where each lives today:

| Selector | Identifies | Where today |
|---|---|---|
| Download host (`dl_host`) | C2 / staging infra | regex'd from `payload` at read-time |
| Download filename | multi-arch dropper | regex'd at read-time |
| Sample SHA-256 → family/ssdeep | the payload | `sample_sha256` + catalog |
| HASSH / client banner | the *tool* | raw `{job="cowrie"}` only |
| Public-key fingerprint reuse | distributed botnet | raw `{job="cowrie"}` only |
| Credential set / command sequence | the script | reconstructable by `session_id` |

The **method** (manual first, deliberately): pick a recurring value on a *tight*
selector, filter sessions to it, see what *else* is constant — the co-constant
selectors are the campaign's signature; the source IPs exhibiting it are its
footprint. We learn which selectors are tight vs. loose by staring at *our*
co-occurrence. That learning is the *input* to any automated clustering, so:

- **L0 — have it:** top-N tables per selector. *"What's out there."*
- **L1 — cheap next:** promote selectors to schema fields + a **pivot dashboard**
  (template variable on `dl_host`/HASSH → co-occurring arch/creds/samples/IPs).
  *The instrument that teaches the clustering rules.*
- **L2 — position, build-at-trigger:** a compact, **insert-only session-summary
  record** (per session: src_ip, ASN, cred-hash, cmd-seq-hash, dl_hosts, dropped
  hashes, HASSH, arch, first/last seen) — a clean feature dataset that outlives
  Loki's 30-day retention and is exactly what a future correlator reads. Design
  now, build once L1 says which features matter. Insert-only fits the **Trust &
  audit** theme.
- **L3 — deferred:** automated correlator emitting **named campaign objects** +
  connected-components / similarity clustering + novel-campaign alerting. Only
  specifiable *after* L1.

### 3a. TTP characterization — from a cluster to a profile

The campaign ladder (§3) answers *"which observations belong together."* It does
**not** answer *"what do they do"* — the operator's second goal, attacker-TTP
detail. A campaign object should carry a **TTP profile**, and that profile has two
layers, cheapest first:

- **Deterministic ATT&CK mapping (rides on the schema).** A rule table maps
  observed actions to MITRE ATT&CK techniques and tags events/sessions:
  `wget|curl` of a binary → **T1105** (Ingress Tool Transfer), appending an SSH key
  to `authorized_keys` → **T1098.004**, `chmod +x` + exec → **T1059/Execution**,
  reading a planted `.env` → **T1552.001** (Credentials in Files). Cheap,
  explainable, no model in the loop — a per-action tag on `{job="events"}` or a
  column on the L2 session-summary record. The technique-set per campaign *is* a
  structured TTP fingerprint, and a never-before-seen technique is itself a
  novelty signal.
- **LLM narration (Claude).** Feed a session or campaign transcript to Claude for
  a plain-English TTP narrative, an intent classification, and a **novel-technique
  flag** ("this doesn't match a known pattern, look at it"). **Haiku 4.5** for
  cheap per-session triage; **Opus 4.8** for campaign-level synthesis. Output is a
  primary content source for the digest (§2: "notable sessions / what's new in
  tradecraft") and an annotation on the L3 campaign object.

**Signal depends on interaction depth.** Low-interaction pots yield thin profiles
(a request, a dropped file); the rich, multi-step TTP chains that make narration
worthwhile come from **high-interaction** sessions — see
`docs/high-interaction-pots-plan.md`, which is the upstream feedstock for this
layer. Build-at-trigger: deterministic ATT&CK tagging can land with the L2 store;
LLM narration follows the digest job (§2 / Phase 3), which is its delivery vehicle.

### 4. Session replay

Two fidelities:

- **Event-timeline replay** (cheap): `{job="events"} | json | session_id="X"`
  ordered into a transcript — cross-protocol, builds on the existing drilldown
  dashboards via a `session_id` template variable. Right first cut.
- **True TTY replay** (later): Cowrie's asciinema `.cast` / ttylog playback —
  higher fidelity but Cowrie-specific, and **the cast files aren't shipped
  off-box today**. Pulling them is a new exfil-from-an-untrusted-host path that
  must respect the one-way log-shipping security model. Depth increment with a
  real constraint, not a freebie.

### 5. Outbound feed publishing — the worker pattern, inverted

Contributing back to ThreatFox (IOCs) / MalwareBazaar (samples) is the existing
catalog **worker pattern inverted**: a publisher polls for samples/IOCs *not yet
pushed* to feed X, pushes them, and writes a `done` row for
`source="published:threatfox"`. DB-as-queue gives crash-safety and no
double-submission for free (`malware-catalog/CLAUDE.md`). It is the **most
trust-sensitive** item — publishing is irreversible and indexed — so it needs
per-feed **opt-in gating** (like `profiles: [triage]`), a disclosure policy
(don't leak operator infra, don't re-submit what came from the feed), and an
outbound write credential.

## Verified finding — the provenance join

The catalog **does** persist provenance: `sources(sha256, src_ip, url,
timestamp)`, populated by `add_source()` and exposed via `SampleDetail.sources`.
So sample→IP and sample→URL pivots are queryable today.

**But two join keys are dropped at ingest.** The capture-writer sidecar records
`session_id` in `<sha256>.capture.json`, yet `add_source(sha256, src_ip, url,
filename)` has no `session_id` or `honeypot` parameter and neither is a column in
`sources`. Consequence: **a captured sample cannot be pivoted back to its
originating session transcript, or to which sensor caught it.** This severs the
bridge between *malware campaign* (catalog-side: family, ssdeep, C2 IOCs) and
*attack campaign* (session-side: IPs, HASSH, infra). Closing it = add two columns
+ thread them through `add_source()` and the `metadata` addon's POST. Cheap now;
unrecoverable later (sessions age out of Loki at 30 days). This *is* the L2 join.

## Cross-cutting concerns

- **Secrets.** Every action except event-timeline replay needs an outbound
  credential (SMTP/webhook, ThreatFox key, MalwareBazaar key). This is the first
  theme to introduce outbound **write** credentials — the natural forcing
  function for the "real secrets management" item under **Trust & audit**.
  Proceed on `.env` for now, document each as a secret from day one, migrate later.
- **Egress.** These add deliberate outbound connections from infra hosts (never
  honeypots) to third parties — fine under the security model (infra is hardened,
  not air-gapped) but a new traffic class to UFW-allow and document. All new
  compute sits on log-stack (alerter + digest) and the catalog host (publisher),
  keeping logic off the untrusted boxes.
- **Capture gap — honeypot egress.** The single highest-signal alert ("a box that
  should only *receive* attacks is now *initiating* traffic") probably isn't
  captured today — we ship `auth.log` + `syslog`, not egress/conntrack. Best
  alert in the set may require closing this capture gap first (UFW/conntrack
  egress logging from the honeypot host, shipped like other host logs).
  Intersects `docs/incident-response-plan.md` (breakout detection).

## Phases

1. **Schema promotion (no-regret prerequisite).** The full version of this is its
   own plan — `docs/normalized-schema-plan.md` (lean core + governed `meta`) —
   and this phase is its first slice: land the `meta` keys this plan depends on
   (`login_success` for the successful-auth alert; `dl_host`/`dl_filename`/
   `client_fingerprint`/family as campaign selectors *and* novelty keys) by
   enriching the per-honeypot Vector `remap` transforms and
   `honey-pots/CLAUDE.md`. Do not start the phases below before it lands. Unblocks
   pivoting, novelty alerting, and campaign correlation simultaneously.
2. **Threshold + sample-novelty alerting.** Provisioned Grafana alert rules under
   `provisioning/alerting/` for security-model-violation events + sensor-dark +
   `new_sample`; one contact point; notification policy with severity routing
   (page vs. digest vs. dashboard).
3. **Digest job.** Render-and-send job on log-stack reading Loki + catalog APIs;
   contents = top infra/tooling/payloads, new samples/families, notable sessions,
   plus the digest-tier alerts from phase 2.
4. **Pivot dashboard (campaign L1).** Template-variable drilldown on the promoted
   selectors — the campaign-learning instrument.
5. **Provenance join.** Add `session_id` + `honeypot` to `sources`; thread through
   `add_source()` and the `metadata` addon POST. Enables sample → session
   transcript and malware↔attack campaign joins.
6. **Session replay (event-timeline).** `session_id` transcript panel on the
   existing drilldown dashboards.
7. **(Build-at-trigger) Session-summary store (campaign L2)** — insert-only
   feature record; design after phase 4 reveals the features that matter.
8. **(Build-at-trigger) Outbound publishing** — ThreatFox/MalwareBazaar publisher
   worker, opt-in gated, with disclosure policy.
9. **(Build-at-trigger) Campaign correlator + novel-campaign alerting (L3)** —
   only after L1/L2.
10. **(Build-at-trigger) TTP characterization (§3a).** Deterministic ATT&CK
    tagging with the L2 store; Claude-driven narration as a digest content source.
    Richest once high-interaction sessions exist (`high-interaction-pots-plan.md`).

## Open questions (resolve before BACKLOG)

1. **Notification channel.** Shared channel (one ntfy topic, self-hostable on
   log-stack over Tailscale, or a Slack/Discord webhook) vs. per-operator email?
   *Lean: shared channel — fits the multi-operator roadmap; first outbound-write
   secret.*
2. **Novelty scope for v1.** Confirmed: **sample-novelty only** (free, catalog).
   New `dl_host` / HASSH / family novelty rides on phase 1 schema promotion; IP
   novelty is **dropped** as noise.
3. **Egress capture in scope here?** Capture honeypot outbound so breakout
   *can* be alerted on, vs. leave to **Trust & audit** / incident-response.
4. **Digest format & cadence** — email vs. chat post vs. committed markdown;
   daily vs. weekly.
5. **Outbound disclosure policy** — which feeds, what's shareable, how to avoid
   re-submitting feed-sourced samples and leaking operator infra.
6. **TTP characterization split (§3a)** — how much rides on deterministic ATT&CK
   tagging vs. LLM narration, and whether narration waits on high-interaction
   sessions to be worth the spend. *Lean: deterministic tagging first (free,
   explainable); narration when the digest job + deep sessions both exist.*

## Graduation to BACKLOG

The no-regret prerequisite and the alerting/digest core can graduate as soon as
Q1 and Q4 are answered; campaign L2/L3 and outbound publishing stay in this plan
until their build triggers fire.

- [ ] Phase 1 — promote `url`/`dl_host`/`dl_filename` + client fingerprints into the normalized schema (`vector.toml` per honeypot + `honey-pots/CLAUDE.md`)
- [ ] Phase 2 — provisioned Grafana alert rules (security-model violations, sensor-dark, `new_sample`) + contact point + severity-routed notification policy
- [ ] Phase 3 — digest job on log-stack (Loki + catalog APIs); digest-tier alerts routed in
- [ ] Phase 4 — campaign pivot dashboard (selector template variable → co-occurrence)
- [ ] Phase 5 — add `session_id` + `honeypot` to catalog `sources`; thread through `add_source()` + `metadata` addon
- [ ] Phase 6 — event-timeline session replay on the drilldown dashboards
- [ ] (Trigger) session-summary store, outbound publisher, campaign correlator
- [ ] (Trigger) TTP characterization (§3a) — ATT&CK tagging on the L2 store + Claude narration into the digest
