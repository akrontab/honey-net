# Multi-Operator Host Access — Plan

Graduation of the **Reach & multi-operator** theme in `docs/!VISION.md` and a
refinement of the `BACKLOG.md` item *"multiple operators with their own user
accounts with sudo access for host management; maintain key-based logins."*

Goal: let several humans administer the fleet as **named, individually
revocable identities**, while the fleet itself trusts **one rotatable anchor**
controlled by the control plane — so a honeypot or network compromise is answered
by rotating a single credential, not re-keying every host. Operator identity is
managed **in the control plane, not in `honey-net.json`** (which stays a pure
server manifest). No softening of the `CLAUDE.md` security model (key-only,
Tailscale-gated, hardened sshd).

This is a *plan*. The architecture is **decided** — phased A → B on a dedicated
bastion gateway (see below). The remaining forks (Q1–Q4) are smaller and can be
settled as the BACKLOG items are picked up.

## Scope & timing — plan, not a build order

This captures the *target shape*; it is **not** a signal to build now. honey-net
is solo-operated today, so standing up a bastion + CA would be premature — a
public ingress, a single point of failure, and a cert pipeline solving a
multi-operator problem that doesn't exist yet.

**Build trigger:** implement when a *second operator actually joins*, or when an
audit/compliance requirement hardens — not before. Until then:

- The one piece worth pulling forward even solo is replacing the single
  *distributed* root key with a single *rotatable* anchor; that improves today's
  compromise-response posture regardless of operator count.
- If honey-net stays solo indefinitely, the lighter fallback (operators on the
  tailnet + restrictive Tailscale ACLs) may be all it ever needs — the bastion is
  conditional on real multi-operator use, not a foregone conclusion.

Writing it now earns one thing: avoiding lock-in. The bastion-vs-tailnet topology
shapes how the tailnet is structured, so fixing the target prevents painting into
a corner later.

## Current state (what we're changing)

| Aspect | Today |
|---|---|
| Remote admin identity | Single shared `root`, one key in `/root/.ssh/authorized_keys` |
| sshd policy | `AllowUsers root`, `PermitRootLogin prohibit-password`, `PasswordAuthentication no`, port 65022 on `tailscale0` only (`server-config/sshd_hardening.conf`) |
| `honey` service user | su-only, **no SSH**, runs rootless Docker — *unaffected by this plan* |
| Source of truth | `honey-net.json`; one `ssh_key` per server (the root key) |
| Audit | `{job="auth"}` ships `auth.log` to Loki, but every action is just "root" |

Two weaknesses: no attribution (every action is "root"), and the single key is
distributed *as the access credential itself* — so rotating it is a fleet-wide
re-key. The redesign separates **operator identity** (many, managed centrally)
from the **fleet access credential** (one, rotatable at will).

## Design direction

Three principles came out of review:

1. **Operators are managed in the control plane, not `honey-net.json`.** The
   server manifest stays about servers. Operator identity/keys live in the
   control-plane layer (a small store on the bastion — see Q3).
2. **The fleet trusts a single, rotatable anchor.** Every host trusts *one*
   credential the control plane holds. Compromise response — honeypot escape or
   broader network compromise — becomes "rotate the anchor, re-trust the fleet,"
   not "touch N hosts." Funneling access through one channel also gives a single
   place to audit every connection and command.
3. **Operators stay off the tailnet; one gateway bridges in.** Operator machines
   never join the tailnet — a single **bastion gateway** is the only way in. They
   reach it from the public internet (cert-gated) and it `ProxyJump`s onward to
   fleet hosts over the tailnet. Tailnet membership stays *infrastructure-only*
   (any non-infra node is then immediately suspect), and a compromised operator
   laptop never gets overlay L3 — only a logged SSH session at the chokepoint, so
   it can't scan or pivot across the network.

These converge on a **dedicated bastion gateway**: a hardened VM that is the sole
public admin ingress, runs the control plane, and holds the fleet's single trust
anchor. It is an SSH *application* gateway (ProxyJump), **not** a subnet router —
operators get a session, never L3 to the overlay. Two trust boundaries result:
*operator → bastion* (public edge — cert/key-only, fail2ban, monitored) and
*bastion → fleet* (tailnet — the single rotatable anchor, still invisible to the
public internet). A stolen operator credential reaches only the bastion, never the
fleet anchor.

**Accepted trade-off:** keeping operators off the tailnet *requires* a public
ingress on the bastion — a deliberate reversal of today's "no public admin
surface" for this one node. Worth it because it concentrates all admin exposure
into one hardened, cert-gated, monitored chokepoint instead of trusting every
operator to run Tailscale correctly.

### Options (with trade-offs)

| # | Model | How operator access works | Rotation / revocation | Audit surface | Build cost | Main risk |
|---|---|---|---|---|---|---|
| **A** | **Bastion + single fleet key** | Operators SSH to the mgmt host (per-operator accounts live only here), then `ProxyJump` to fleet hosts using one shared key held only on the mgmt host. | Rotate the one fleet key + re-push its pubkey to hosts. | One channel — mgmt-host session logs capture every hop. | Low (+1 VM, mostly SSH config). | Mgmt host is a single point of failure **and** a high-value target; its compromise hands over the standing fleet key. |
| **B** | **SSH certificate authority** | Hosts trust one CA pubkey (`TrustedUserCAKeys`); the control plane signs **short-lived** operator certs (e.g. 8–24 h); operators connect *directly* over Tailscale presenting the cert. | Stop signing (cert TTL expires) or publish a KRL; rotate the CA key to invalidate everything at once. | Per-issuance signing log on the mgmt host + cert principal/serial in each host's `auth.log`. | Medium (signing flow + cert plumbing). | CA **private** key is now the crown jewel; no single session chokepoint unless paired with A. |
| **C** | **Control-plane-mediated only** | Operators never get a raw host shell; every action runs through `honey.py` on the mgmt host, which holds the anchor and logs each command. | Rotate the one anchor. | Strongest — every command audited at the control plane. | Medium (need a logged command/shell surface). | Weak for ad-hoc interactive incident response; an escape hatch (ProxyJump) is still needed for break-glass debugging. |

**Decided — phased A → B on a dedicated management host, with C as the default path:**

- **Start with A.** Stand up the management host, give it the single fleet key,
  point operators through it via `ProxyJump`, keep per-operator accounts on the
  mgmt host only. This delivers *single-rotatable-key* + *single audit channel*
  quickly, and immediately addresses the review: `honey-net.json` stays clean and
  a compromise is a one-key rotation.
- **Layer B next.** Introduce the SSH CA so hosts trust only the CA pubkey and
  the *standing* shared key goes away — short-lived certs give real revocation
  (TTL/KRL) and per-operator attribution without distributing keys to hosts.
- **C rides on top.** Make the logged `honey.py` path the default for routine
  ops; reserve direct `ProxyJump` shells for break-glass.

The end state: hosts trust one CA pubkey, the control plane mints time-boxed
per-operator certs, and the worst-case response to *any* compromise is rotating
the CA key — exactly the "single key, rotated at will" property the review
called for.

### Break-glass & multi-cloud

`PermitRootLogin prohibit-password` stays during rollout so a botched change can't
lock everyone out. The real break-glass — for when the **bastion or the tailnet
itself** is down — is the provider's out-of-band console, which is
**provider-specific**: Linode LISH today, but AWS (EC2 Serial Console / SSM),
Hetzner (web console), etc. all differ. The plan must treat break-glass as a
per-provider capability, not assume LISH. This intersects the **Cloud portability**
theme — see `docs/aws-eks-migration-plan.md`.

Failure-mode handling (including the single-anchor rotation runbook this design
enables) is worked separately in `docs/incident-response-plan.md`.

## Phases

1. **Bastion gateway** — provision a **dedicated** hardened VM (new
   `honey-net.json` server entry, reuses `server-config` hardening) that is the
   sole public admin ingress and joins the tailnet; it runs the control plane and
   holds the single fleet key. Per-operator identity lives here, nowhere else.
   Harden the public edge (cert/key-only, fail2ban, monitored) and keep tailnet
   ACLs to infrastructure nodes only. Separate from data-plane backends for
   blast-radius isolation.
2. **Funnel (Option A)** — fleet sshd trusts only the mgmt-host key; operators
   reach hosts via `ProxyJump` through the mgmt host; session logging shipped to
   `{job="auth"}`. Root stays as break-glass.
3. **Certs (Option B)** — hosts trust a CA pubkey (`TrustedUserCAKeys`); control
   plane issues short-lived per-operator certs; remove the standing shared key.
4. **Offboarding & rotation** — remove an operator centrally; document anchor / CA
   rotation (the compromise runbook) and KRL for immediate revocation.
5. **Backend + multi-cloud** — extend to `log-stack` and `malware-catalog`
   (self-contained `setup.sh`, reachable over SSH); document per-provider
   break-glass.

## Alternatives considered

| Option | Verdict |
|---|---|
| **Bastion gateway + single rotatable anchor** (above) | **Recommended target.** Operators off the tailnet, central identity, one credential to rotate on compromise, one audit chokepoint. |
| Operators on the tailnet + restrictive Tailscale ACLs | The lighter path — and likely sufficient if honey-net stays solo. Avoids a public ingress, but every operator runs Tailscale, the device list churns with personal machines, and it leans on ACL config rather than a structural boundary. Preferred only *until* there are real multiple operators. |
| Per-operator keys installed on every host (earlier draft) | Superseded by review. Distributes N×M keys; revoke/rotate touches every host; no single rotatable anchor and no single audit chokepoint. |
| Tailscale SSH + ACLs | Deferred. Offloads identity to Tailscale but departs from the sshd model (`--ssh=false`) and couples host auth to Tailscale's control plane. Could complement, not replace, the bastion. |
| Manual `useradd` per host | Rejected. Not reproducible, no source of truth, no clean revocation. |

**Decided:** architecture = phased **A → B**; topology = **dedicated bastion
gateway** (operators off the tailnet, single cert-gated public ingress).

## Open questions (resolve before BACKLOG)

1. **Shell policy** — allow direct `ProxyJump` shells for operators, or force
   control-plane-mediated commands (Option C) with `ProxyJump` reserved for
   break-glass? *Lean: mediated-default, ProxyJump for break-glass.*
2. **Anchor custody** — single fleet key (A) / CA private key (B): keep on the
   mgmt host, or hold offline / HSM-style with manual signing for higher
   assurance?
3. **Operator store** — flat `authorized_keys` + forced-command on the bastion,
   vs. a small declarative `operators.json` *in the control plane* (explicitly
   **not** `honey-net.json`)?
4. **Bastion public edge** — hardening on the internet-facing side: cert-gating
   from day one, source-IP allowlist (if operators have stable IPs), non-standard
   port, fail2ban tuning? *Lean: cert-gated + fail2ban; revisit a source
   allowlist.*

## Graduation to BACKLOG

Once Q1–Q4 are answered:

- [ ] Provision hardened bastion gateway (sole public ingress + tailnet, `server-config` hardening, holds the anchor)
- [ ] Operator identity managed centrally on the bastion (off `honey-net.json`)
- [ ] Fleet sshd trusts only the anchor; `ProxyJump` access verified end-to-end
- [ ] Session/command audit from the mgmt host shipped to `{job="auth"}` and visible in Grafana
- [ ] (Phase 3) SSH CA: hosts trust CA pubkey; short-lived cert issuance via the control plane; standing key removed
- [ ] Single-anchor rotation runbook (compromise → rotate → fleet re-trust → KRL old certs) — cross-ref `docs/incident-response-plan.md`
- [ ] Per-provider break-glass documented (LISH + others)
