# Testing — Strategy

How honey-net proves a change is safe *before* it reaches the fleet, and how it
confirms the fleet still works after. This is the cross-cutting strategy doc — it
names the **test tiers**, what each covers, where each runs, and the conventions
new tests follow. Individual features link here rather than re-deciding how to test.

## The problem this fixes

Today **every test needs live infrastructure**. The per-package `test.py` smoke
tests SSH into a deployed box; `check_*`/`test_loki` query the running fleet. The
**control plane itself — the pure-Python composition and validation in `lib/` and
`scripts/` — has no tests at all.** You cannot today assert "this manifest produces
that `setup.sh`," or "two honeypots claiming the same port is rejected," without
spinning up a Linode.

That is backwards: the logic most likely to break on a refactor (assembly,
validation, schema) is the cheapest to test offline, and is the part with zero
coverage. The structured port composer (`docs/reconfigure-plan.md`, Chunk A) is
pure functions over the manifest and package files — it is the natural anchor for
the project's first **offline unit tier**, and this doc graduates with it.

## Boundary — what this owns

Owns the **test taxonomy + conventions + the coverage map** (which tier covers
what, and the gaps). It does **not** own:

- The **post-deploy verification gate** — wiring `check_*`/`test_*` to run
  automatically after a push and block on failure. That is `docs/deployment-plan.md`
  Phase 4; it *consumes* the tiers named here.
- **CI execution** — running the offline tiers on every commit. That defers to the
  Operational-maturity theme (`docs/!VISION.md`) / deployment-plan Phase 5; this doc
  defines *what* CI runs, not the runner.

## The tiers

| Tier | Scope | Needs infra? | Runs when | Tooling |
|---|---|---|---|---|
| **1. Unit** | pure-Python control plane: port composition, collision/rule validation, manifest schema, `lib/` helpers | **no** | every change · pre-commit · CI | `pytest` |
| **2. Contract / lint** | static assertions on *generated artifacts* and *package declarations* (no CRLF, normalized `meta` keys, no `up --build`, declared ports ⊆ manifest) | **no** | every change · CI | `pytest` (+ `shellcheck`) |
| **3. Smoke (per-package)** | one live deployment answers on its ports, container up, log file present | yes — one box | post-deploy · on demand | `test.py` via `honey.py test` |
| **4. Operational checks** | live-fleet health: Loki stream freshness, disk, SSH keys | yes — fleet | scheduled · post-deploy | `check_logs` / `check_disk` / `check_ssh_keys` |
| **5. Integration / e2e** | provision → deploy → attack → event lands in Loki; reconfigure idempotency | yes — ephemeral / local | triggered | future harness (see below) |

Tiers 1–2 are new and the focus of the near-term work. Tiers 3–4 exist and stay
as-is. Tier 5 is sketched and build-at-trigger.

The dividing line is **infra**: tiers 1–2 must run on a laptop with no network, no
SSH, no cloud — they read repo files and assert on the Python that processes them.
A test that reaches for `state.json`'s real IPs or opens a socket belongs in tier
3+.

## Conventions

- **`pytest`**, in a top-level `tests/` tree mirroring the source: `tests/unit/`,
  `tests/contract/`, fixtures under `tests/fixtures/` (sample manifests, expected
  golden artifacts). Dev-only deps in a new `requirements-dev.txt` (`pytest`, and a
  snapshot helper if wanted) — kept out of the runtime `requirements.txt` that ships
  to servers.
- **Offline tiers touch nothing live.** No `subprocess` to `ssh`/`docker`/
  `terraform`, no real `state.json`, no sockets. Feed the code a fixture manifest and
  assert on its return value or the bytes it writes to a `tmp_path`.
- **Golden-file tests for generated artifacts.** The assembled `setup.sh`,
  top-level `docker-compose.yml`, and merged `vector.toml` are deterministic outputs
  of `lib/package.py` — snapshot them and diff. A golden diff is the signal a
  composition refactor changed behavior; review and re-bless intentionally.
- **Every generated-artifact test asserts no CRLF.** Files written by Python and
  deployed to Linux must be LF-only (`open(..., newline="\n")`); a stray `\r\n`
  silently breaks bash/YAML on the box. One assertion (`b"\r\n" not in data`) on each
  generated artifact guards the whole class of bug cheaply.
- **Per-package smoke tests keep the `_lib` idiom** (`select_server`, SSH :65022)
  and stay runnable individually and via `scripts/test_honeypot.py`.
- **Run targets:** `pytest` (tiers 1–2, the default dev loop) · `python honey.py
  test` (tier 3, against a chosen server) · `python honey.py check-logs|check-disk`
  (tier 4).

## Coverage map — current vs target

| Area | Today | Target tier |
|---|---|---|
| Port composition / collision / rules (`lib/package.py`) | **none** | 1 — unit |
| `setup.sh` / compose / `vector.toml` assembly | **none** | 1 + 2 — golden + no-CRLF |
| Manifest schema (required keys, types) | **none** | 1 — unit |
| Normalized `meta` key contract per pot | **none** (deferred, `normalized-schema-plan.md` Q1) | 2 — contract lint |
| `reconfigure` phase dispatch (first-boot vs idempotent) | n/a (unbuilt) | 1 + 2 — unit + bash lint |
| Per-honeypot liveness | `test.py` (cowrie, mysql, smb, ftp, http) | 3 — smoke (keep) |
| Loki freshness / disk / keys | `check_*` | 4 — checks (keep) |
| Full provision→attack→Loki path | **none** | 5 — integration (trigger) |

## Near-term: validate the port composer (the anchor)

The first concrete unit + contract suite, landing **with** the composer
(`reconfigure-plan.md` Chunk A/B). These are all offline — a fixture manifest and
fixture `package.toml` files drive them:

1. **Collision is rejected** — two components on one server declaring the same port
   raises with both names and the port (`'cowrie' and 'webtrap' both bind :22`).
2. **Reserved ports rejected** — any package declaring `65022` (real SSH) is an error.
3. **Bridge cross-check** — a bridge-network pot whose `package.toml` `ports` disagree
   with its `docker-compose.yml` `ports:` is flagged; host-network pots (cowrie) are
   exempt (no compose `ports:` by design).
4. **Host set derives correctly** — `collect_ports(server)` returns the union of
   component ports; `lib/server.py` displays it (the hand-kept `honey-net.json`
   `ports` array is gone).
5. **Generated `setup.sh` is golden + LF-only** — assembling a known server matches
   the fixture, the dangerous first-boot steps (`ufw --force reset`, sshd port move,
   `tailscale up`) appear under the `firstboot` branch only, and the `ufw allow` lines
   match the derived port set.
6. **Reconfigure path is config-only** — the `HONEYNET_PHASE=reconfigure` dispatch
   calls only the idempotent `configure_*` steps, never a first-boot step (assert by
   parsing the assembled script's dispatcher, plus `shellcheck` on the bash).

This suite is the proof the composer works and the regression net for every later
package added.

## Integration tier (sketch — build at trigger)

Tier 5 is the expensive one; deferred until a refactor bites or CI exists.

- **Local pot-in-a-container harness** — run one honeypot's compose locally, drive
  its protocol against loopback, assert (a) a raw `{job=<pot>}` line and (b) a
  normalized `{job="events"}` event with the right `event_type` + standard `meta`
  keys. Catches the "logs to stdout but the file never appears / Loki stream empty"
  class without a Linode.
- **Reconfigure idempotency** — run the assembled `setup.sh` twice with
  `HONEYNET_PHASE=reconfigure` against a throwaway container; assert UFW/sshd
  converge and nothing first-boot fires.

Trigger: the first composition/reconfigure bug that escapes tiers 1–2, or CI
standing up — whichever first.

## Relationship to other plans

- **`deployment-plan.md`** — Phase 4's post-deploy gate runs tiers 3–4 (and any fast
  tier-1/2 relevant to the change) automatically and blocks on failure; this doc is
  the menu it picks from. Phase 5's CI runs tiers 1–2 on every commit.
- **`normalized-schema-plan.md`** — its deferred Q1 lint ("each pot emits its
  declared standard `meta` keys") graduates here as a tier-2 contract test when a
  third pot's `meta` lands.
- **`incident-response-plan.md`** — shares the `check_*` operational tier as the
  signal for self-healing / break-glass; this doc owns their definition.
- **`!VISION.md`** (Operational maturity) — the theme this serves: "a honeypot that
  silently stopped logging is worse than one that is down" is the failure tiers 4–5
  exist to catch at deploy time, not days later.

## Graduation to BACKLOG

- [ ] `tests/` + `pytest` + `requirements-dev.txt` scaffold (tier 1–2 home)
- [ ] Port-composer unit tests — collision, reserved-port, bridge cross-check, union
- [ ] Golden + no-CRLF tests for assembled `setup.sh` / compose / `vector.toml`
- [ ] `reconfigure` phase-dispatch unit test + `shellcheck` on `setup.sh`/fragments
- [ ] (Trigger) Integration harness — pot-in-a-container + reconfigure idempotency
- [ ] (Trigger) Normalized `meta`-key contract lint — when a third pot lands
- [ ] (Defer) CI runs tiers 1–2 on every commit — to Operational maturity / deployment Phase 5
