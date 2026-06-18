# High-Interaction Honeypots — Plan

New thread under the **Detection & intel depth** theme in `docs/!VISION.md`
("capture a wider slice of attacker behavior"). It is the **interaction-depth**
axis — distinct from `docs/built-in-honeypot-coverage-plan.md`, which is protocol
*breadth*. Breadth widens *which* attacks we see; depth deepens *how much of each
attack* we see.

The premise the operator named: the highest-signal, most novel TTPs come from an
attacker who actually gets in and works — exploring a real filesystem, staging
tooling, attempting lateral movement, hands-on-keyboard. A low-interaction pot
captures the *attempt*; a high-interaction pot captures the *tradecraft*. This is
the richest possible feedstock for the TTP-characterization work in
`docs/operationalizing-intel-plan.md`.

This is a *plan*, not buildable tasks. It is **design-first and gated**: the
containment bar (below) must be specified and met before any high-interaction pot
is built, because this thread deliberately maximizes the one thing the security
model exists to survive.

> **Status: `proposed`.** No work started. The dominant work is containment
> design, not capture; graduation is gated on the threat model (Phase 1) and on
> closing the honeypot-egress capture gap (Phase 2).

## The interaction spectrum — where the fleet sits

| Level | Mechanism | Fleet today | Captures | Risk |
|---|---|---|---|---|
| **Low** | canned responses | `http`, `mysql`, `smb`, `ftp` | the attempt: probes, creds, uploads | minimal — nothing to compromise |
| **Medium** | emulated shell | `cowrie` (SSH/Telnet) | commands, downloads, planted keys | low — emulation is a sandbox |
| **High** | a *real* (contained) system | **none** | full post-exploitation tradecraft | **high — the box can truly be owned** |

Cowrie's emulation is the current ceiling, and sophisticated actors fingerprint
and abandon it. A real contained environment removes that ceiling — at the cost of
a real compromise surface.

## The dominant constraint — containment, not capture

The security model in `CLAUDE.md` is "honeypots are untrusted and expected to be
compromised; everything else is hardened to survive it." High-interaction
**maximizes** that compromise: a real shell *will* be used to attack third
parties, mine, or stage C2. So this plan is mostly a containment design, and the
non-negotiables come first:

- **Egress is default-deny, and logged.** The box that should only *receive*
  attacks must not become a platform that *initiates* them — this is the legal /
  abuse line. Outbound is blocked except the bare minimum that sustains the
  illusion, bandwidth-capped, and fully recorded. This **forces closing the
  honeypot-egress capture gap** that `operationalizing-intel-plan.md` and
  `alerting-plan.md` both flag as deferred.
- **Per-session isolation + reset.** Each session gets a disposable environment;
  snapshot/restore between sessions so one attacker's footprint doesn't bleed into
  the next and a burned environment is thrown away, not cleaned.
- **Full session recording, shipped one-way.** pcap + keystroke/tty + filesystem
  diff, exfiltrated off-box on the existing one-way log-shipping path (note: the
  Cowrie `.cast` files aren't shipped today — same off-box gap called out in
  `operationalizing-intel-plan.md` §4).
- **Stronger isolation boundary.** VM-per-pot (Linode) is the floor; high-
  interaction likely wants nested isolation (microVM / gVisor) and tighter
  Tailscale segmentation around the backend.

## Candidate approaches

| Approach | Shape | Isolation | Notes |
|---|---|---|---|
| **Proxy-to-backend** | Cowrie's proxy mode front-ends a real disposable backend shell, recording all traffic | backend VM is fully disposable | reuses existing Cowrie integration + log path; natural first cut for SSH |
| **Sandboxed real service** | a real daemon in a hardened container + recording sidecar + egress filter | container + host VM | broadest applicability; weakest isolation of the three |
| **MicroVM per session** | Firecracker / Kata microVM spun per session | near-VM isolation, fast reset | strongest containment; most infra to build |

Wrapping an existing high-interaction project is also on the table if one fits the
`docs/wrapping-upstream-honeypots-plan.md` process.

## Phases (design-first, build-at-trigger)

1. **Threat model + containment bar.** Write down the non-negotiables (egress
   default-deny + logging, per-session reset, recording-off-box, isolation tech)
   and the abuse-response posture. **This is the gate** — nothing high-interaction
   builds until it's met.
2. **Egress capture + control on existing hosts.** UFW/conntrack egress logging,
   shipped like other host logs; default-deny outbound policy. Independently
   valuable (closes the breakout-detection gap for `alerting-plan.md` /
   `incident-response-plan.md`) and a prerequisite here.
3. **PoC — one high-interaction pot.** The chosen isolation model (proxy-to-backend
   SSH is the natural first), recording-complete and egress-contained, on a
   **dedicated, larger VM** (a 1 GB Nanode won't hold a real backend + recording).
4. **TTP extraction.** Feed the recorded deep sessions into the
   **TTP-characterization layer** (`operationalizing-intel-plan.md`) — ATT&CK
   mapping + LLM narration. This is where the interaction depth converts into the
   operator's "novel TTPs" goal.
5. **(Build-at-trigger) Generalize.** Additional high-interaction protocols /
   environments once the PoC proves the containment model holds in the wild.

## Open questions (resolve before BACKLOG)

1. **Isolation technology** — hardened container + egress filter vs. microVM
   (Firecracker/Kata) vs. full VM-per-session? *Lean: start proxy-to-backend with a
   disposable backend VM; evaluate microVM if container isolation proves too thin.*
2. **Reset cadence** — per-session vs. time-boxed vs. on-compromise-detection?
3. **Host sizing / cost** — high-interaction won't fit the Nanode model; how big a
   dedicated VM, and does that change the per-sensor cost story enough to matter?
4. **Realism ceiling** — how real is real *enough* before the detection-evasion
   arms race stops being worth it?
5. **Outbound allowance** — strictly default-deny, or a tightly-monitored sliver
   (DNS, a fake update endpoint) to sustain the illusion without enabling abuse?
6. **Legal / abuse posture** — the operator-facing policy if a contained box is
   nonetheless used to reach a third party.

## Relationship to other plans

- **`CLAUDE.md` security model** — the line this plan must hold; high-interaction
  stresses it hardest.
- **`incident-response-plan.md`** — a breakout is *expected* here, not exceptional;
  the egress-capture and response playbook overlap directly.
- **`operationalizing-intel-plan.md`** — the **consumer**: deep sessions are the
  best input to TTP characterization and to true TTY session replay (§4).
- **`alerting-plan.md`** — Phase 2 egress capture lands the highest-signal
  breakout rule that plan defers.
- **`built-in-honeypot-coverage-plan.md`** — orthogonal axis (breadth vs. depth);
  a protocol could exist in both a low- and a high-interaction form.
- **`aws-eks-migration-plan.md`** — its VM-vs-orchestration isolation trade-off
  analysis informs the isolation-tech choice (Q1).
