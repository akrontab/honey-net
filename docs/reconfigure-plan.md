# Reconfigure — Plan

Graduates **Phase 2 of `docs/deployment-plan.md`** (gap 5 — the live host-config
path). It turns out the clean way to build that path also closes a latent design
smell — ports declared twice, as un-introspectable bash — so this plan bundles two
chunks built **as one effort**:

- **Part A — structured port composer.** Promote honeypot ports from imperative
  `ufw allow` bash into declarative per-package metadata a Python composer reads,
  enabling collision detection and a single source of truth.
- **Part B — `reconfigure.py`.** Re-apply hardening config and reconcile ports on a
  *running* box over Tailscale :65022, without a reprovision and without re-opening
  :22.

A is built first because B consumes it: the reconcile in B needs a declarative
"desired port set," which is exactly what A produces. (Built together rather than
sequenced because the project is greenfield and single-operator — no live stakes,
so the clean end-state lands in one move.)

## Boundary — what this plan owns

Owns the **port-composition layer** (package metadata, validation, UFW generation,
the `setup.sh` assembly refactor) and the **live host-config push** (`reconfigure.py`,
the first-boot/idempotent split of `setup.sh`). It does **not** own:

- **Secret / `.env` push** (gap 6) — deliberately separate so a config push can
  never clobber a secret. Deferred to deployment-plan Phase 3.
- **Verification gate + rollback + `--dry-run`** — deployment-plan Phase 4.
- **Backend host-config parity** — `log-stack` / `malware-catalog` have their own
  self-contained `setup.sh` outside `server-config/`; v1 targets honeypot servers,
  where the trigger (a new honeypot port) bites. Backend parity is a noted follow-on.

The invariant both parts preserve (from `!DESIGN.md`): **config stays declared in the
package** — A keeps the port declaration in each package's `package.toml`, it just
makes it structured instead of bash. Nothing is centralized into the control plane
that wasn't already.

## Part A — the structured port composer

Today `lib/package.py` already composes the **service** surface in structured Python
— it parses each component's `docker-compose.yml`, merges the vector services and
`vector.toml`s, and generates the top-level compose. The one part still done by dumb
string concatenation is `provision.py._stage_honeypot` building `setup.sh` via
`setup += fragment.read_text()` — and that's exactly where ports hide as bash. A
finishes the pattern `lib/package.py` already set.

### A1 — `deploy/package.toml` per package

Each port-binding package declares its ports as data:

```toml
# honey-pots/cowrie/deploy/package.toml
ports = [22, 23]
```

Addons that bind nothing (`metadata`, `malware-sender`) declare `ports = []` (or omit
the file — treated as none). TOML matches the existing `vector.toml` precedent and
`tomllib` is already imported in `lib/package.py`. The field is intentionally minimal;
the file is the home for any future declarative package facts (see open Q2).

### A2 — `collect_ports` + validation, in `lib/package.py`

A new `collect_ports(server) -> dict[int, str]` reads every component's `package.toml`
and builds a `{port: package_name}` map, enforcing:

| Rule | Failure |
|---|---|
| **No collision** | two components on one server claim the same port → `impossible config: 'cowrie' and 'webtrap' both bind :22 on 'mysql-ssh'` |
| **Reserved ports** | any package declaring `65022` (real SSH) → error |
| **Bridge cross-check** | a bridge-network pot whose `package.toml` ports disagree with its `docker-compose.yml` `ports:` → error. Host-network pots (cowrie) have no compose `ports:` by design and are exempt — `package.toml` is their sole machine-readable source |

The collision case is the headline: today two pots claiming a port surfaces only at
runtime when the second container fails to bind. A catches it at compose time, before
any deploy.

### A3 — derive the host port set; drop the manifest array

`collect_ports` makes the host's port set **derived** (the union of component ports).
The hand-kept `honey-net.json` `"ports"` array — which nothing functional reads (only
`lib/server.py:28`, for display) — is **dropped**. `lib/server.py` computes the union
from `package.toml` for its listing. One source, no drift.

### A4 — generate the UFW lines; fragments lose them

The composer emits a `configure_ports()` bash function (an `ufw allow <port>/tcp` per
derived port) into the assembled `setup.sh`. Each `fragment.sh` **drops its `ufw allow`
block**. With ports gone, fragments are now **pure service surface** — volume dirs,
chowns, image builds, `up -d` — which sets up Part B's clean phase split.

## Part B — the live host-config path

### B1 — `setup.sh` → functions + a phase dispatcher

Refactor `server-config/setup.sh`'s linear steps 1–9 into named functions, classified
by whether they are safe to re-run on a live box:

| First-boot-only (NEVER on reconfigure) | Idempotent config (both phases) |
|---|---|
| apt upgrade/install · Docker + rootless dockerd | `configure_sshd` — drop `sshd_hardening.conf`, **`sshd -t` validate, `systemctl reload ssh`** (never the Port move, never `restart`) |
| `ufw --force reset` + 65022 bootstrap | `configure_sysctl` — copy `99-hardening.conf`, `sysctl --system` |
| sshd **port move** + socket-disable | `configure_fail2ban` — copy jail, `systemctl reload fail2ban` |
| unattended-upgrades · file deploy · Tailscale join + 65022→tailscale0 tighten + `.env` write | (generated) `configure_ports` · `reconcile_ports` |

The base file defines functions only; the **composer appends a generated dispatch
tail**:

```bash
case "${HONEYNET_PHASE:-firstboot}" in
  reconfigure)
    configure_sshd; configure_sysctl; configure_fail2ban
    configure_ports; reconcile_ports ;;
  firstboot)
    firstboot_apt; firstboot_docker; ufw_bootstrap; sshd_move
    configure_sshd; configure_sysctl; configure_fail2ban
    unattended; deploy_files; tailscale_join; write_env
    configure_ports
    fragment_cowrie; fragment_http; fragment_mysql; ... ;;
esac
```

The safety property is **visual and structural**: the `reconfigure` branch lists only
idempotent steps. It is impossible for a reconfigure to reach `ufw --force reset`, the
sshd port move, or `tailscale up` — they aren't called.

### B2 — fragments → functions, gated to first-boot

Because ports moved out (A4), a fragment is entirely service surface. Wrap each
fragment body as a `fragment_<name>()` function; the dispatch tail calls them only in
the `firstboot` branch. On reconfigure, no fragment runs — only the conf reloads and
the port reconcile.

### B3 — one artifact, two phases (anti-drift)

`provision` and `reconfigure` run the **same assembled `setup.sh`**, differing only by
`HONEYNET_PHASE`. First-boot and live-config are literally the same code, so they
cannot drift. `firstboot` is the default, so **`provision.py` needs no change** beyond
moving its assembly into `lib/package.py`.

### B4 — full reconcile (prune)

`reconcile_ports()` (generated, with the derived desired set baked in) reconciles UFW:
parse `ufw status` for broad `ALLOW IN ... Anywhere` **tcp** rules (the 65022 rule is
`on tailscale0`-bound → excluded; outgoing excluded), and `ufw delete allow <port>/tcp`
any whose port ∉ the desired set. `configure_ports` runs just before it (add side), so
a pot removed from the manifest has its port closed without a reprovision.

### B5 — `scripts/reconfigure.py` (mirrors `redeploy.py`, over :65022)

- `select_server` → `tailscale_ip` from `state.json` (honeypot servers only in v1).
- Assemble the **same** package `provision` builds (the assembly logic + `_CONF_FILES`
  lift from `provision.py` into `lib/package.py` so both share it).
- SCP the minimal config set (assembled `setup.sh` + the 3 conf files) to
  `/root/<name>/` over :65022.
- SSH run `HONEYNET_PHASE=reconfigure bash /root/<name>/setup.sh`; the SSH call
  returning success *is* the proof sshd survived. Print resulting `ufw status`.
- Register in `honey.py` `COMMANDS` as `reconfigure`.

## Touchpoints

| Path | Change |
|---|---|
| `honey-pots/*/deploy/package.toml`, `addons/*/deploy/package.toml` | **new** — declare `ports` |
| `lib/package.py` | `collect_ports` + validation; UFW generation; absorb `setup.sh` assembly + `_CONF_FILES` from `provision.py` |
| `honey-pots/*/deploy/setup/fragment.sh` (7×) | drop `ufw allow`; wrap body as `fragment_<name>()` |
| `server-config/setup.sh` | steps 1–9 → functions; composer appends the dispatch tail |
| `scripts/provision.py` | call shared assembly in `lib/package.py` (behavior unchanged) |
| `scripts/reconfigure.py` | **new** — live host-config push over :65022 |
| `honey.py` | register `reconfigure` in `COMMANDS` |
| `honey-net.json` | drop the `ports` arrays |
| `lib/server.py` | compute port union from `package.toml` for display |
| `server-config/CLAUDE.md`, `honey-pots/CLAUDE.md` | document `package.toml`, the `HONEYNET_PHASE` convention, and that fragments no longer open ports |
| `docs/deployment-plan.md` | check Phase 2; link here |

## Testing

Per `docs/!TESTING.md`, this feature is the anchor for the new **offline tier-1/2**
suite — all pure-Python, fixture-driven, no infra:

- collision rejected · reserved-65022 rejected · bridge cross-check · union derivation
- golden + LF-only assembled `setup.sh` (dangerous steps under `firstboot` only; UFW
  lines match the derived set)
- `reconfigure` dispatch calls only `configure_*` (+ `shellcheck` on the bash)

These land **with** the composer and are the regression net for every pot added later.

## Open questions

1. **`--dry-run` now, or Phase 4?** A path that can `ufw delete` rules warrants a
   preview (planned adds/deletes + conf diffs, no apply). Cheap to add here; the parent
   plan currently sequences it in Phase 4. *Lean: include a lightweight `--dry-run` in
   `reconfigure.py` given the destructive prune; full gate/rollback stays Phase 4.*
2. **Other `package.toml` fields?** A `terminal`/up-d-ordering flag (which fragment
   runs `up -d` last) is today encoded implicitly in fragment bash. Promoting it to
   `package.toml` would let the composer order the dispatch tail explicitly. *Lean:
   ports only for now; add fields when a second consumer appears (YAGNI).*
3. **Backend parity timing** — when do `log-stack` / `malware-catalog` get a
   `reconfigure` path? *Lean: defer until a backend host-config edit needs to reach a
   live box; honeypot-first matches the trigger.*

## Graduation to BACKLOG

- [ ] A1 — `package.toml` in each port-binding package
- [ ] A2 — `collect_ports` + collision / reserved / bridge-cross-check validation
- [ ] A3 — derive host port set; drop `honey-net.json` `ports`; `lib/server.py` union
- [ ] A4 — generate `configure_ports`; strip `ufw allow` from fragments
- [ ] B1 — `setup.sh` → functions + composer-appended phase dispatch tail
- [ ] B2 — fragments → `fragment_<name>()`, gated to first-boot
- [ ] B4 — `reconcile_ports` (prune stale UFW rules)
- [ ] B5 — `scripts/reconfigure.py` over :65022; register in `honey.py`
- [ ] Offline tier-1/2 test suite (see `!TESTING.md`) lands with the composer
- [ ] Docs — `package.toml` + `HONEYNET_PHASE` conventions; check deployment Phase 2
