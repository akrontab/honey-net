# Vision

Where honey-net is headed and why. This is the high-altitude layer: directional
themes and their rationale, not committed dates and not buildable tasks.

**How this fits the other docs** — ideas mature down an altitude pipeline:

```
VISION.md  ──►  deep plan file   ──►  BACKLOG.md   ──►  DESIGN.md / code
(direction,     (aws-eks-         (ready, scoped    (built; documents
 themes, why)    migration.md…)    tasks)            current state)
```

- A theme here graduates to its **own plan file** in this folder (the pattern
  `docs/aws-eks-migration-plan.md` set) once it's worth a real design.
- A plan graduates to **`BACKLOG.md`** once it's decomposed into buildable steps.
- Don't put dates or task checklists here — those belong downstream.
- The dependencies *between* plan files are tracked in `docs/!DEPENDENCIES.md`.

## North star

honey-net should become a **self-running threat-intelligence sensor network**:
cheap, disposable honeypots at the edge capturing real attacks, an immutable
pipeline turning raw sessions into normalized intel, and that intel made useful —
queried, pivoted, alerted on, and shared — without the operator babysitting
infrastructure. The PoC has proven the shape; the work ahead is depth (better
intel), reach (more sensors, more protocols), and maturity (run it like a
product, not a demo).

The non-negotiable constraint stays the security model in `CLAUDE.md`: honeypots
are untrusted, everything else is hardened to survive their compromise. Every
theme below has to hold that line.

## Themes

### Detection & intel depth

*Direction.* Capture a wider slice of attacker behavior and extract more signal
from what we capture. More protocols (telnet, RDP, HTTP/web-app, SMTP) to widen
the aperture; a richer normalized schema so cross-honeypot questions stay
single-expression; campaign and actor clustering on top of the normalized stream;
IOC pivoting and outbound export (STIX/TAXII, MISP) so the catalog isn't a
dead-end store.

*Why.* The two-stream logging and malware catalog already make honey-net a
collector. The leverage now is analytical — turning sessions and samples into
attributed campaigns and shareable indicators is what makes the data worth more
than the sum of its events.

*Pointers.* The first protocol graduation — an HTTP/web-app honeypot — is worked
in `docs/http-honeypot-plan.md`. The richer normalized schema (lean core +
governed `meta`) that makes cross-honeypot questions single-expression — and
de-couples the dashboards from Cowrie — is worked in
`docs/normalized-schema-plan.md`. Malware-side enrichment has its own plan in
`malware-catalog/PLAN.md`. New honeypot protocols slot into the self-describing
package model (`docs/!DESIGN.md`) with no control-plane changes.

### Reach & multi-operator

*Direction.* Grow from a handful of Nanodes to a distributed fleet —
geographically spread sensors that catch region-specific attacks — and support
multiple operators running it together, each with their own audited, key-based,
sudo-capable account for host management.

*Why.* More vantage points mean better coverage and the ability to see targeting
differences. Multi-operator is the difference between a personal project and
something a small team can run; it's already surfaced in `BACKLOG.md` as a
near-term want.

*Pointers.* Multi-operator host access is worked in `docs/multi-operator-plan.md`
(refines the queued `BACKLOG.md` item). Fleet growth is gated by provisioning
ergonomics — see *Operational maturity*.

### Cloud portability & infra evolution

*Direction.* Avoid single-provider lock-in. Multi-cloud Terraform so honeypots
can stand up on whatever's cheapest or best-positioned, and a credible path to a
container-orchestrated deployment for operators who want it — without abandoning
the cheap-VM model that gives per-honeypot hypervisor isolation for free.

*Why.* Portability is resilience: providers ban honeypot traffic, change pricing,
or go down. It also keeps the project honest about the isolation trade-offs
between VM-per-honeypot and shared-kernel orchestration.

*Pointers.* The Kubernetes/AWS path is fully worked in `docs/aws-eks-migration-plan.md`,
including the isolation and cost trade-offs vs. the current Linode model.
Multi-cloud Terraform sits under "Maybes" in `BACKLOG.md`.

### Trust & audit integrity

*Direction.* Harden the one property a compromised honeypot must never break:
the audit trail. Move toward provably append-only storage (object-lock /
write-once), automated tamper and drift detection, routine key rotation, and
real secrets management for the API keys the enrichment workers depend on.

*Why.* The security model promises an immutable audit trail and off-box log
shipping. As the fleet and the value of the data grow, "immutable by convention"
should become "immutable by construction" — the system of record has to survive
not just a honeypot compromise but operator error.

*Pointers.* Builds directly on the immutability guarantees in `CLAUDE.md` and the
insert-only catalog records in `malware-catalog/CLAUDE.md`.

### Operationalizing the intel

*Direction.* Close the loop from capture to action: alerting on novel
indicators and high-signal events, scheduled intel digests, attacker session
replay, and feeding indicators back out to the community feeds we already pull
from (abuse.ch, MalwareBazaar).

*Why.* Dashboards answer questions you think to ask; alerting and digests surface
what you didn't. A sensor network that only collects is half a system — the value
is realized when the intel drives a notification, a block, or a contribution back.

*Pointers.* This theme has graduated into focused, atomic plans:
`docs/operationalizing-intel-plan.md` keeps the campaign maturity ladder, digests,
outbound publishing, and the provenance join; **alerting** (detection rules → a
PoC dashboard → custom notification services for novel attacks and campaigns) is
its own plan, `docs/alerting-plan.md`; and the **visualization surface** (the
dashboard overhaul onto the normalized contract — workflow tiers + per-protocol
deep-dives) is `docs/dashboard-overhaul-plan.md`, which owns everything that
renders. All sit on the normalized `{job="events"}` stream and the Grafana/Loki
stack (`log-stack/`). Outbound sharing pairs with the export work under
*Detection & intel depth*.

### Operational maturity

*Direction.* Run honey-net like a product: CI for the Python control plane and
package configs, provisioning health checks and self-healing, cost visibility
across the fleet, and observability of the control plane itself — not just the
honeypots it deploys.

*Why.* Every other theme assumes provisioning is cheap and reliable. As sensor
count and operator count rise, manual `honey.py` runs and eyeballed deploys stop
scaling. Maturity here is the multiplier that makes reach and portability
affordable.

*Pointers.* Centers on the control plane (`honey.py`, `scripts/`, `lib/`) and the
self-describing package model (`docs/!DESIGN.md`). Host/network failure modes and
the response playbook are worked in `docs/incident-response-plan.md`.

### Maintenance & code health

*Direction.* Keep the system honest with itself as it grows: pay down technical
debt before it compounds, catch documentation drift the moment code moves
underneath it, triage incoming defects so real bugs don't get lost in the noise,
and hold a verification-and-testing discipline that proves a change works — both
the per-package `test.py` checks and manual verification of a live deploy —
before it's called done. This is the steady-state hygiene loop that runs
*underneath* every other theme, not a one-time cleanup.

*Why.* Every contract in `CLAUDE.md` — single source of truth in
`honey-net.json`, self-describing packages, the hardcoded filesystem paths, the
two Loki streams — is only true as long as the code and the docs still agree.
Doc staleness is uniquely corrosive here because the `CLAUDE.md` files are
load-bearing: they're read as ground truth by operators *and* by Claude, so a
stale doc doesn't just mislead, it actively steers future work wrong. Untriaged
bugs and untested changes erode the same trust the security model depends on — a
honeypot that silently stops logging is worse than one that's down. Debt already
has a named example: the HTTP pot shipped ahead of the normalized-schema keystone
and now needs a Cowrie-shaped retrofit (see `docs/!DEPENDENCIES.md`), exactly the
kind of shortcut this theme exists to keep visible and scheduled.

*Pointers.* Distinct from *Operational maturity*, which owns the CI
*infrastructure* and the running-system health (provisioning checks, cost,
control-plane observability); this theme owns the *content* that flows through it
— the debt backlog, the test coverage, the doc-vs-code accuracy, and the triage
discipline itself. `BACKLOG.md` is the intake for graduated defects and debt
(e.g. the queued "remove honeypot-specific references from the README"); the
existing `honey-pots/*/test.py`, `scripts/test_*.py`, and `log-stack/test_loki.py`
are the verification surface to grow and wire into CI when *Operational maturity*
stands one up. No plan file yet — this graduates to one (and into
`docs/!DEPENDENCIES.md`) when the debt warrants a real design rather than
case-by-case paydown.
