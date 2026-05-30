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
  `docs/aws-eks-migration.md` set) once it's worth a real design.
- A plan graduates to **`BACKLOG.md`** once it's decomposed into buildable steps.
- Don't put dates or task checklists here — those belong downstream.

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
in `docs/http-honeypot-plan.md`. Malware-side enrichment has its own plan in
`malware-catalog/PLAN.md`. New honeypot protocols slot into the self-describing
package model (`docs/DESIGN.md`) with no control-plane changes.

### Reach & multi-operator

*Direction.* Grow from a handful of Nanodes to a distributed fleet —
geographically spread sensors that catch region-specific attacks — and support
multiple operators running it together, each with their own audited, key-based,
sudo-capable account for host management.

*Why.* More vantage points mean better coverage and the ability to see targeting
differences. Multi-operator is the difference between a personal project and
something a small team can run; it's already surfaced in `BACKLOG.md` as a
near-term want.

*Pointers.* Multi-operator accounts are queued in `BACKLOG.md`. Fleet growth is
gated by provisioning ergonomics — see *Operational maturity*.

### Cloud portability & infra evolution

*Direction.* Avoid single-provider lock-in. Multi-cloud Terraform so honeypots
can stand up on whatever's cheapest or best-positioned, and a credible path to a
container-orchestrated deployment for operators who want it — without abandoning
the cheap-VM model that gives per-honeypot hypervisor isolation for free.

*Why.* Portability is resilience: providers ban honeypot traffic, change pricing,
or go down. It also keeps the project honest about the isolation trade-offs
between VM-per-honeypot and shared-kernel orchestration.

*Pointers.* The Kubernetes/AWS path is fully worked in `docs/aws-eks-migration.md`,
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

*Pointers.* Sits on the normalized `{job="events"}` stream and the Grafana/Loki
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
self-describing package model (`docs/DESIGN.md`).
