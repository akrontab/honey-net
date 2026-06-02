# Deployment — Plan

First graduation from the **Operational maturity** theme in `docs/!VISION.md`:
"every other theme assumes provisioning is cheap and reliable… manual `honey.py`
runs and eyeballed deploys stop scaling." This plan names the **deployment
pattern** — what kinds of change there are, and the supported path to push each —
so a change reaches the fleet the same way every time instead of as a one-off
SSH session.

This is a *plan*, not buildable tasks.

## Boundary — what this plan owns

Owns the **change-delivery pattern**: the taxonomy of change types, the mechanism
each rides, the two operator runbooks (fresh provision; change to a live net),
and the gaps where a change type has *no supported live path today*. It does **not**
own the heavier Operational-maturity automation — CI for the control plane, cost
visibility, self-healing — which stay in the theme and graduate separately; this
plan is the manual pattern those later automate. Host/network *failure* recovery
(a box dies, a key is compromised) is `incident-response-plan.md`; this plan is
the *intentional* push path, not the break-glass one.

## The model — three surfaces, one source of truth

`honey-net.json` is the single source of truth (CLAUDE.md). Every deploy is a
reconciliation of one of **three surfaces** of a server toward what the manifest
and the package directories declare:

| Surface | What it covers | First-provision tool | Live-update tool |
|---|---|---|---|
| **Infra** | the VM itself (Linode plan, region, existence) | `provision` (terraform) | `deprovision` / `teardown` (destroy); resize = replace |
| **System config** | host hardening — sshd on :65022, sysctl, fail2ban, UFW rules, honeypot port openings | `provision` → `setup.sh` steps 1–9 + fragment, **over port 22** | **— none —** |
| **Service** | compose stack, package code/config, dashboards, `.env` | `provision` (same `setup.sh` tail) | `redeploy` over Tailscale :65022 |

The asymmetry is the whole problem. `provision` does **all three** on a greenfield
box over port 22 (before the box has hardened itself off the public internet).
`redeploy` does **only the service surface** over the Tailscale port 65022 — by
design it "does not touch system configuration," and its rsync **excludes `.env`**
and protects `volumes/`. So the moment a change touches **system config** or a
**secret** on an *already-provisioned* box, there is no supported path: the operator
either reprovisions (heavy, and `provision` skips live servers unless `--force`) or
hand-edits over SSH (the eyeballed deploy this theme exists to kill).

## The change taxonomy — what you push, and how

Every change an operator makes maps to one row. The first four are covered today;
the last three are the gaps this plan closes.

| # | Change | Example | Surface(s) | Path today | State |
|---|---|---|---|---|---|
| 1 | **New server → live net** | add a honeypot VM | infra + config + service | `provision --server NAME` (terraform runs; threads LOKI_HOST/CATALOG_URL) | ✅ works; ordering caveat below |
| 2 | **Retire a server** | decommission a pot | infra | `deprovision --server NAME` | ✅ covered |
| 3 | **Service/package update** | edit honeypot config, compose, detector, a dashboard JSON | service | `redeploy --server NAME` (rebuild changed svc + `up -d`) | ✅ works; no gate/rollback |
| 4 | **Re-thread an IP** | log-stack re-IPs → LOKI_HOST | service (`.env`) | re-thread + `redeploy` peers | ⚠️ partial (see gap 6) |
| 5 | **Host-config change** | new honeypot port, sshd/sysctl/fail2ban/UFW edit | config | **none live** → `--force` reprovision or manual SSH | ❌ **gap** |
| 6 | **Secret / `.env` change** | rotate an enrichment key; add a notification-channel token | config (env) | **none** — `redeploy` excludes `.env` → manual SSH | ❌ **gap** |
| 7 | **Operator-set change** | add/rotate an operator key (`operators.json`) | config | reprovision or manual | ❌ **gap** (pairs with multi-operator) |

**Favor reconciliation over recreation.** On a live, attacked fleet a full
reprovision is the expensive, riskier move (new VM, re-hardening window, lost
local forensic state on `volumes/`). The pattern's goal is that **rows 5–7 each
get a live, idempotent, Tailscale-side path** so reprovision is reserved for
infra-surface change (row 1/2) — not forced by a one-line sysctl edit.

## The two runbooks (the pattern, stated)

These are the operator-facing halves of the request: "fresh provision" and "deploy
to an already-provisioned net." Both already exist in tooling; Phase 1 just writes
them down as *the* way.

**A. Fresh provision (greenfield).** `provision` →
terraform creates VMs → per server in dependency order (backends first;
log-stack before malware-catalog before honeypots): gen Tailscale key → stage
package → SCP over **:22** → run `setup.sh` (hardens, moves SSH to :65022, joins
tailnet, starts stack) → poll tailnet for the 100.x IP → thread `LOKI_HOST` /
`CATALOG_URL` to the next server. Secrets collected up front so the run is
unattended. Idempotent at the server granularity: re-running skips live servers
unless `--force`.

**B. Change to a live net.** Pick the surface, then the tool:
- *Service surface* → `redeploy --server NAME` (rsync to `/opt`, rebuild changed
  services, `up -d`). The 90%-case daily driver.
- *Infra surface* → `deprovision`/`provision --server` (add/remove a box).
- *Config / secret surface* → **the missing path** (gaps 5–7), today only
  `--force` reprovision or manual SSH.

The seam between A and B is the **port boundary**: A runs over :22 because the box
hasn't hardened itself yet; B runs over :65022 (Tailscale-only) because by then it
has. Any new live mechanism (Phases 2–3) lives on the **:65022 side** — never
re-opens :22.

## The gaps — lean recommendations

### Gap 5 — live host-config path (`reconfigure`)

The single highest-value gap: a way to push a hardening-conf edit or a new honeypot
port to a *running* box without reprovisioning. Lean approach — **make `setup.sh`'s
config steps idempotent and re-runnable, then run them over :65022**:

- Split `setup.sh` (and each `fragment.sh`) into **first-boot-only** steps (move
  SSH off :22, join tailnet) versus **idempotent config** steps (write hardening
  confs, `ufw allow`, sysctl apply, fail2ban reload, open honeypot ports). The
  config steps must be safe to re-run — `ufw allow` already is; conf files are
  overwrite-then-reload.
- A `reconfigure.py` (Tailscale :65022, like `redeploy`) ships the conf files +
  re-runs **only** the idempotent config steps, never the SSH-move/tailnet-join.
  This keeps the self-describing-package idiom (config still declared in
  `server-config/` + the pot's `fragment.sh`) and adds no new dependency.

*Considered alternative:* a config-management tool (Ansible). Rejected for a small
fleet — it re-centralizes off the bash/self-describing model and is a heavy new
dependency for what is a handful of overwrite-and-reload steps. Revisit if the
fleet or operator count makes hand-rolled idempotency the bottleneck. See open Q1.

### Gap 6 — secret / `.env` push

`redeploy` deliberately excludes `.env`, so there is **no** path to update a secret
on a live box. This bites the moment alerting Phase 2 lands (Telegram/Discord
tokens) or an enrichment key rotates. Lean — a **narrow, guarded `.env`-only
push** (Tailscale :65022): write the new `.env`, `up -d` to restart the consuming
service, touch nothing else. Keep it separate from `redeploy` so a routine code
deploy can never silently clobber a secret, and vice-versa. This is the first
forcing function for the **secrets-management** cross-cutting thread
(`docs/!DEPENDENCIES.md`) — where `.env` is the source of truth, how it is
generated, and how it is protected are that thread's to answer. See open Q2.

### Gaps 4 / 7 — re-threading and operator-set

Re-threading (row 4) is a special case of gap 6 — the changed value (`LOKI_HOST`,
`CATALOG_URL`) lives in `.env`, so it rides the same secret-push path once that
exists. Operator-set changes (row 7) are config-surface and ride the `reconfigure`
path, but the *content* (operator keys, sudo model) is owned by
`multi-operator-plan.md`; this plan only supplies the delivery mechanism.

## Verification & rollback (the act-safely half)

Today a deploy is fire-and-forget: `redeploy` restarts the stack and exits; nothing
confirms the box still logs. The verification surface already exists but is
**not wired into the deploy** — `check_logs.py` (Loki stream freshness),
`check_disk.py`, `test_honeypot.py`, `test_loki.py`, the per-package `test.py`.

The pattern's "prove it worked" half, phased after the push paths exist:

- **Post-deploy gate** — after any push, run the relevant `check_*`/`test_*` and
  report pass/fail, so "a honeypot silently stopped logging" (the failure mode
  VISION calls worse than being down) is caught at deploy time, not days later.
- **Rollback** — `redeploy` already stages into a temp dir and rsyncs into `/opt`;
  capturing the prior `/opt/<server>` package enables a one-step revert. Lean:
  snapshot-before-rsync on the box, `--rollback` restores it and `up -d`.
- **`--dry-run`** for the live paths — `deprovision` already has one; `redeploy`
  and the new `reconfigure`/secret-push paths should too, so an operator sees the
  diff before it lands.

## Relationship to other plans

- **`incident-response-plan.md`** — that plan owns *unintentional* recovery (host
  failure, key compromise, self-healing); this owns the *intentional* push. They
  meet at the verification surface (both consume `check_*`/`test_*`) and at
  self-healing, which is an automated re-application of this plan's reconcile.
- **`multi-operator-plan.md`** — supplies the *content* of row 7 (operator keys,
  sudo model); this plan supplies the live-config delivery mechanism it needs.
- **`alerting-plan.md`** — its Phase 2 channel tokens are the first concrete
  trigger for gap 6 (secret push).
- **Secrets-management** (cross-cutting thread, `docs/!DEPENDENCIES.md`) — gap 6 is
  one of its forcing functions; this plan defers the `.env`-as-source-of-truth
  question there.
- **Self-describing package model** (`docs/!DESIGN.md`) — the invariant the
  `reconfigure` path must preserve: config stays declared in `server-config/` and
  each pot's `fragment.sh`, discovered at runtime, never centralized.

## Phases (graduation order)

1. **Document the pattern as-is** — ✅ **done**: the surface model, the change
   taxonomy, and the two runbooks (A/B above) live in the root `CLAUDE.md`
   ("Deployment" section) so operators and Claude read one canonical "how to push X."
   *Zero code.* This is the plan's core deliverable — the "pattern" the request asks
   for.
2. **(Trigger) Live host-config path** — modularize `setup.sh`/`fragment.sh` into
   first-boot vs. idempotent-config steps + a `reconfigure.py` over :65022 (gap 5).
   Trigger: the first time a hardening conf or new honeypot port must reach a live
   box without a reprovision.
3. **(Trigger) Secret / `.env` push** — guarded `.env`-only push over :65022
   (gap 6). Trigger: alerting Phase 2 tokens, or the first key rotation. Coordinates
   with the secrets-management thread.
4. **Verification gate + rollback** — wire `check_*`/`test_*` as a post-deploy gate;
   snapshot-and-revert for `redeploy`/`reconfigure`; `--dry-run` on the live paths.
   Trigger: a bad deploy bites, or CI stands up (whichever first).
5. **(Build-at-trigger) CI / self-healing** — hand the now-explicit pattern to the
   Operational-maturity automation: CI runs the gate on every change; self-healing
   re-applies the reconcile on drift. Defers to the theme.

## Open questions (resolve before BACKLOG)

1. **Host-config delivery** — idempotent `setup.sh` modules re-run via
   `reconfigure.py` over :65022 (lean) vs. a config-management tool (Ansible) vs.
   accept reprovision-only for config. *Lean: modularize + `reconfigure.py` — keeps
   the bash/self-describing idiom, no new dependency, reuses the :65022 path.*
2. **`.env` source of truth** — where the canonical `.env` for a live box lives and
   how it is pushed without clobbering volumes or code. *Lean: a separate
   secret-push tool, not folded into `redeploy`; full answer deferred to the
   secrets-management thread.*
3. **Rollback granularity** — per-service vs. whole-`/opt/<server>` package
   snapshot. *Lean: whole-package snapshot before rsync — simplest one-step revert,
   matches how `redeploy` already stages.*
4. **Add-server-to-live-net ordering** — when row 1 adds a box that needs an
   existing peer's IP (or whose IP a peer needs), is a re-thread + restart of the
   peer required, and is that safe live? *Lean: document the dependency-order
   caveat in Phase 1; only build re-thread automation if it bites.*
5. **One tool or many** — `reconfigure` + secret-push + rollback as flags on
   `redeploy`, or distinct scripts in `honey.py`'s `COMMANDS`. *Lean: distinct
   scripts — keeps each push path's blast radius explicit (a code deploy can't
   touch secrets), consistent with the one-script-per-concern control plane.*

## Graduation to BACKLOG

Phase 1 (the written pattern) graduates immediately — it is documentation of
existing tooling. Phases 2–5 are build-at-trigger and graduate as their triggers
fire.

- [x] Phase 1 — surface model + change taxonomy + A/B runbooks, in the root
      `CLAUDE.md` ("Deployment" section)
- [ ] (Trigger) Phase 2 — `reconfigure.py` + idempotent `setup.sh`/`fragment.sh`
      split (gap 5)
- [ ] (Trigger) Phase 3 — guarded `.env`/secret push (gap 6)
- [ ] Phase 4 — post-deploy verification gate + rollback + `--dry-run` on live paths
- [ ] (Build-at-trigger) Phase 5 — CI gate + self-healing (defers to Operational
      maturity)
