# Built-In Honeypot Protocol Coverage — Plan

Part of the **Detection & intel depth** theme in `docs/!VISION.md` ("more
protocols to widen the aperture"). This is the **parent roadmap** for *built-in*
honeypots — pots whose behavior we author in this repo, not third-party projects
fitted to honey-net via the wrap process.

It surveys what the fleet covers today, proposes the protocols worth adding next,
and ranks them. It is deliberately **not** a build order: each protocol that
graduates gets its **own child plan** (the pattern `docs/http-honeypot-plan.md`
set) when there's a real trigger to build it. This file is the menu and the
rationale, not a commitment to build all of it.

> **Status: `proposed`.** Survey + ranked candidate list. No package work has
> started. Individual protocols graduate to their own plan file → `BACKLOG.md`
> when prioritized.

## Built-in vs. wrapped — the distinction this plan draws

| | Built-in | Wrapped |
|---|---|---|
| Code origin | We author the service (full control of log schema) | Third-party upstream we don't control |
| Examples | `mysql/`, `smb/`, `ftp/`, `http/` | `cowrie/` (SSH/Telnet), `heralding/` (multi-cred ref) |
| Normalized mapping | Trivial — we emit the schema directly | Adapter `remap` translates an alien format |
| Reference | `honey-pots/CLAUDE.md` (new package) | `docs/wrapping-upstream-honeypots-plan.md` |

This plan covers **only the built-in column.** Where an upstream pot already does
a protocol well (Cowrie owns SSH + Telnet; Heralding sweeps the pure-credential
protocols), a built-in version has to justify itself with capture value the wrap
doesn't give us — otherwise wrap it instead.

## Current coverage

| Protocol | Ports | Package | Kind | Captures |
|---|---|---|---|---|
| SSH / Telnet | 22, 23 | `cowrie` | wrapped | full PTY sessions, commands, dropped binaries, planted keys, creds |
| MySQL | 3306 | `mysql` | **built-in** | wire-protocol auth + SQL queries against a decoy crypto-exchange DB |
| SMB / CIFS | 139, 445 | `smb` | **built-in** | NTLM credential attempts, connection events |
| FTP | 21, 60000-60010 | `ftp` | **built-in** | creds, fake financial/crypto filesystem browsing, uploaded malware |
| HTTP / HTTPS | 80, 443 | `http` | **built-in** | requests, scanner probes, credential POSTs, web-shell/file uploads |
| (multi-cred) | many | `heralding` | wrapped (ref, undeployed) | credential attempts across 12 protocols — capture only, no session |

**What the fleet is blind to today:** the entire NoSQL/cache tier (Redis, Mongo),
PostgreSQL (the other half of relational scan traffic), the cloud-native control
planes (Docker/K8s API) that drive most cryptominer deployment, mail (SMTP), and
remote-desktop (RDP) — the last two explicitly named as wanted in `!VISION.md`.

## Selection criteria

A protocol earns a built-in pot when it scores well on:

1. **Attack volume** — is this surface actively, broadly scanned? Blind spots
   with high hit-rate beat exotic protocols nobody touches.
2. **Intel richness** — does interaction yield campaign signal (exploit payloads,
   creds, tooling fingerprints) or feed the malware pipeline (dropped binaries)?
3. **Fit to the lean precedent** — implementable as a small Python/asyncio service
   (the `mysql/` shape) inside the **1 GB Nanode** budget. No heavyweight runtime.
4. **Non-duplication** — not already well-covered by Cowrie, and worth more than
   simply enabling the protocol in a Heralding wrap (i.e. session/decoy value, not
   just credential capture).
5. **Decoy synergy** — can it carry the existing financial/crypto lure (the
   `coinvault_prod` / fake-wallet narrative) so a multi-pot host tells one story?

## Candidates, tiered

### Tier 1 — build first (cleanest fit, highest blind-spot value)

#### PostgreSQL (5432) — the MySQL twin
The direct structural mirror of `mysql/`: implement the PG wire protocol startup
+ `SASL`/`md5`/`cleartext` auth, accept everything, serve a decoy DB. PG is
scanned at MySQL-comparable volume and we see none of it. Reuses the `mysql/`
package shape almost wholesale (decoy DB, query handler, packet builders) — the
lowest-effort, highest-confidence addition. Carries the `coinvault` decoy directly.
Standard `meta`: `database`, `login_success`, `auth_method` (`md5`/`scram`/`password`).

#### Redis (6379) — top unauth-RCE vector, trivial protocol
RESP is one of the simplest wire protocols to implement, and unauthenticated
Redis is one of the most-exploited internet services: attackers use `CONFIG SET
dir/dbfilename` + `SAVE` to write cron jobs or `authorized_keys`, and `SLAVEOF`/
`REPLICAOF` module-load chains for RCE. A built-in pot that accepts commands and
logs the `CONFIG SET`/`SET`/`SLAVEOF` payloads captures the *exploit attempt
itself* — high-grade campaign intel, and the written payloads (cron lines, keys,
module URLs) feed straight into the existing inbox/malware pipeline. Emit
`command` events with `payload` = the RESP command.

#### Docker Remote API (2375, optionally 2376) — cloud-native cryptominer magnet
Exposed unauthenticated Docker daemons are a premier cloud attack: scanners hit
`GET /version`, then `POST /containers/create` + `/start` to launch miners,
often mounting the host root. The API is HTTP/JSON, so this rides the `http/`
package's stdlib-server precedent — emulate the handful of Docker API endpoints
scanners probe and **log the container-create spec** (image, cmd, binds, env).
That spec is dense intent intel (which miner image, which C2, host-escape via
`/:/host` bind). Captures pulled image refs as IOCs. Highest novelty-to-effort
ratio after Redis.

### Tier 2 — strong, more implementation surface

#### SMTP (25, 587, 465) — VISION-named; spam/relay/phish intel
Capture `EHLO`/`AUTH LOGIN`/`AUTH PLAIN` credential brute force and open-relay
probes (`MAIL FROM`/`RCPT TO` to third-party domains). Logs the relay targets and
message envelopes — direct signal on spam and phishing campaigns. A modest state
machine over asyncio; accept-all auth, advertise relay, never actually send. Emit
`login` (AUTH) and `command` (envelope verbs).

#### MongoDB (27017) — NoSQL ransom-wipe twin of MySQL
Binary OP_MSG/OP_QUERY wire protocol; accept-all, serve decoy collections.
Internet-exposed Mongo is routinely wiped-and-ransomed (`readme`/`RECOVER`
collections demanding crypto) — a pot captures the ransom note and the dropped
collection, plus recon queries. Structurally a `mysql/`-shaped build but the
binary BSON framing is more work than PG. Carries the crypto decoy well.

#### RDP (3389) — VISION-named; connection-intel only
Full RDP (NLA/CredSSP/TLS) is too heavy for a built-in pot, but the **X.224
Connection Request** carries the `mstshash=<username>` cookie and the client
negotiates capabilities before any crypto — a low-interaction pot can capture the
attempted username, client build, and TLS/credSSP negotiation fingerprint without
implementing the full stack. Scoped strictly to connection intel; if that proves
thin, this is a candidate to *wrap* (Heralding has RDP, currently disabled)
rather than deepen the build.

### Tier 3 — niche / UDP / revisit on demand

Lower priority — either narrow audiences, UDP plumbing the fleet doesn't do yet,
or substantial overlap with Heralding's credential sweep. Documented so the menu
is complete; build only on a specific trigger.

| Protocol | Port | Why it's interesting | Why it waits |
|---|---|---|---|
| **LDAP** | 389 | JNDI/Log4Shell-style callback capture; AD recon queries | callback intel niche; pairs better with the HTTP pot's exploit-path logging |
| **VNC** | 5900 | RFB auth-challenge capture | Heralding already covers; thin without framebuffer emulation |
| **SIP / VoIP** | 5060 | toll-fraud `REGISTER`/`INVITE` scanning is very high-volume | UDP-first; narrow attacker population |
| **SNMP** | 161 | community-string brute force, device recon | UDP; recon-only, low session value |
| **TFTP** | 69 | IoT/router malware staging | UDP; mostly subsumed by what Cowrie already pulls |
| **MQTT** | 1883 | growing IoT broker scanning | emerging volume; revisit as IoT targeting grows |
| **Elasticsearch** | 9200 | mass-scanned; CVE probes, data-wipe ransom | HTTP/JSON — could be an `http/` persona rather than its own pot |

## Cross-cutting notes

- **Schema is free.** Every built-in pot here emits the normalized
  `{job="events"}` contract directly (`honey-pots/CLAUDE.md`) — `protocol` is a
  string field, so none of these need a schema change. They land in every
  cross-cutting dashboard and alert with **zero dashboard edits** the moment they
  fill the standard `meta` keys for their capabilities. New per-protocol
  deep-dive dashboards are the only viz work (the `dashboard-overhaul-plan.md`
  tiering already has the slot).
- **No control-plane changes.** All of these slot into the self-describing
  package model — a `honey-pots/<proto>/` directory plus a `honey-net.json`
  entry, no Terraform or root-script edits (the property that made HTTP cheap).
- **Budget & placement.** Each pot is sized for co-tenancy on a 1 GB Nanode
  (`security_opt`, `deploy.resources.limits` per `honey-pots/CLAUDE.md`).
  Natural groupings for new hosts: a **datastore host** (PostgreSQL + Redis +
  MongoDB) and a **cloud-native host** (Docker API + later K8s); SMTP/RDP can
  co-tenant on existing pots. Per-protocol plans decide own-VM vs. co-tenant the
  way `http-honeypot-plan.md` did.
- **UDP is a new capability.** Tier-3 UDP pots (SIP, SNMP, TFTP) would be the
  first UDP services in the fleet — `fragment.sh` UFW rules and the compose port
  mapping need a UDP path proven once. Flagged as a prerequisite, not assumed.
- **Decoy continuity.** The crypto-exchange narrative (`coinvault_prod`, fake
  wallets/keys) should carry across PostgreSQL, MongoDB, and any datastore pot so
  a host that exposes several backends tells one coherent, sticky story.

## Recommendation

Lead with **PostgreSQL** (lowest effort — a near-clone of `mysql/`) to prove the
"second instance of a pattern" is cheap, then **Redis** and the **Docker API**
pot for the biggest blind-spot/intel wins. SMTP and MongoDB follow as Tier-2
when there's appetite; RDP and the Tier-3 set stay parked until a specific need
(or a wrap) makes more sense than a build.

## Graduating a protocol

When a protocol is picked up:

1. Spin its row out into `docs/<protocol>-honeypot-plan.md` (use
   `http-honeypot-plan.md` as the template: why, package shape, engine choice,
   normalized mapping, phases, open questions).
2. Add a `BACKLOG.md` item pointing at that plan.
3. Build against the new-honeypot checklist in `honey-pots/CLAUDE.md`.
4. Update `docs/!DEPENDENCIES.md` if the build depends on another in-flight plan
   (e.g. a UDP pot depending on the UDP-path prerequisite above).
