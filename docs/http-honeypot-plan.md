# HTTP / Web-App Honeypot — Plan

First graduation from the **Detection & intel depth** theme in `docs/VISION.md`:
add an HTTP honeypot package so the network captures web-layer attacks — the
single largest source of opportunistic internet traffic the current pots
(SSH/Telnet, MySQL, SMB, FTP) don't see.

This is a *plan*, not yet buildable tasks. When the open questions below are
settled, the "Graduation to BACKLOG" section becomes the checklist.

## Why HTTP next

- **Volume.** Mass scanners hammer `/`, `.env`, `/wp-login.php`, `/.git/config`,
  Spring/Struts/Log4j paths, and PHP RCE endpoints continuously. It's the highest
  hit-rate surface we're currently blind to.
- **Intel richness.** Request paths, user-agents, and POST bodies are strong
  campaign fingerprints; web shells and dropped payloads feed straight into the
  existing malware pipeline.
- **Clean fit.** It slots into the self-describing package model (`honey-pots/CLAUDE.md`)
  with zero control-plane changes — the same property that made it the cheapest
  theme to prove the VISION → plan → backlog pipeline end to end.

## Package shape

A new `honey-pots/http/` package following the standard layout. Nothing outside
the package directory changes except a `honey-net.json` entry.

```
honey-pots/http/
├── deploy/
│   ├── docker-compose.yml     ← http honeypot service + vector sidecar
│   ├── Dockerfile             ← built-locally Python service (mysql/ precedent)
│   ├── app/                   ← the honeypot web app
│   ├── vector/vector.toml     ← raw {job="http"} + normalized {job="events"}
│   ├── setup/fragment.sh      ← open :80/:443, make volumes + inbox/http
│   └── .env.example
├── CLAUDE.md                  ← protocol, log paths, event mapping, gotchas
└── test.py                    ← smoke test (_lib import pattern)
```

Ports bind to the container, never the host (security model in `CLAUDE.md`);
`fragment.sh` opens UFW for 80/443 and creates `inbox/http/` (`chmod 777`) since
this pot captures uploads.

## Engine choice

| Option | Fit | Cost | Notes |
|---|---|---|---|
| **Custom lightweight Python app** (aiohttp/Flask) | **Recommended** | ~64–128 M | Mirrors the `mysql/` built-locally precedent. Full control of logging schema → trivial normalized mapping. Emulate a small bank of juicy responses (fake login, fake admin, fake `.env`) and log everything else as a probe. |
| SNARE + TANNER (mushmush) | Rich, dynamic | ~300 M+ Redis | Clones real sites, emulates vulns. Heavier — two services plus Redis strains the 1 GB Nanode shared with Cowrie + Vector. |
| Galah (LLM-backed) | Very high interaction | API cost + latency | Generates plausible responses per request via an LLM. Compelling but adds an external dependency and per-request cost; revisit once the cheap version proves traffic volume. |

Recommendation: ship the **custom lightweight app** first (keeps the
Cheaper-Than-Starbucks budget and the clean schema), keep SNARE/TANNER as a
fallback if low-interaction realism proves insufficient to hold attacker sessions.

## Normalized event mapping

Reuses the unified schema in `honey-pots/CLAUDE.md` — `protocol: "http"`, no
schema change. The Vector `remap` transform maps the app's raw log to:

| HTTP activity | `event_type` | Notable fields |
|---|---|---|
| TCP/TLS open | `connect` | `src_ip`, `src_port` |
| Any request | `command` | `payload` = `"<METHOD> <path>"`; user-agent in raw stream |
| Credential POST (login form / Basic auth) | `login` | `username`, `password` |
| File upload / web-shell drop | `download` | `sample_sha256` (written to `inbox/http/`) |
| Connection close | `session_end` | `session_id` |

Requests that don't match a meaningful action still emit `command` so scan
patterns are queryable; nothing is `abort`ed unless it's pure noise.

## Phases

1. **Minimal pot** — custom app serving a fake site (landing page, `/admin`
   login, a handful of honeytoken paths). Raw JSON log to
   `./volumes/logs/http.json`. UFW :80 only.
2. **Normalization** — Vector `remap` to the `{job="events"}` stream; verify
   `connect`/`command`/`login` show up in the cross-honeypot stream.
3. **Sample capture** — accept and persist POST uploads / web-shell writes to
   `inbox/http/`; the existing `metadata` + `malware-sender` addons pick them up
   with no changes.
4. **TLS** — add :443 with a self-signed cert (attackers don't validate); doubles
   the captured surface.
5. **Dashboard** — Grafana panel under
   `log-stack/deploy/grafana/provisioning/dashboards/`: top paths, top
   user-agents, credential attempts, uploads.

## Trade-offs & open questions

- **Realism vs. budget.** Low-interaction won't hold a determined human, but it
  captures the overwhelmingly automated web-scan traffic cheaply. Start cheap;
  the engine table above is the upgrade path.
- **Co-tenant or own VM?** Adding HTTP to an existing honeypot VM shares the 1 GB
  Nanode (Cowrie + Vector already resident). A dedicated `http` server is cleaner
  for blast-radius isolation but adds $5/mo. **Open question** — decide before
  the `honey-net.json` entry.
- **Which decoy app persona?** WordPress-ish, a generic admin panel, or a fake
  internal tool? Persona shapes which scanners engage. **Open question.**
- **Upload abuse.** The pot will be offered as a file drop; cap size and rate in
  the app, and rely on `inbox/http` → `metadata` canonicalization so storage
  stays bounded.

## Graduation to BACKLOG

When the two open questions (own-VM vs co-tenant, decoy persona) are answered,
promote to `BACKLOG.md` as the standard new-honeypot checklist from
`honey-pots/CLAUDE.md`:

- [ ] `honey-pots/http/` package (compose, Dockerfile, app, vector.toml, fragment.sh, .env.example)
- [ ] `CLAUDE.md` documenting the event mapping above
- [ ] `test.py` smoke test
- [ ] `honey-net.json` entry + SSH key pair (new VM) or add to an existing server's `honeypots`
- [ ] Grafana dashboard
- [ ] `python honey.py provision --server <name>`
