# log-stack

Grafana + Loki log visualization for [honey-net](../README.md). Receives structured logs from all honeypot servers over Tailscale VPN and provides pre-built dashboards for attacker analysis.

Grafana and Loki are bound to the Tailscale IP only — never exposed to the public internet.

## Dashboards

| Dashboard | What it shows |
|-----------|--------------|
| Cowrie — Attack Overview | SSH connections, login attempts, top IPs / usernames / passwords |
| Cowrie — Commands | Commands run by attackers, file downloads |
| Telnet Overview | Same as SSH overview, Telnet protocol |
| MySQL Overview | MySQL connections, SQL queries, databases targeted |
| Credential Intelligence | SSH username+password combo analysis, credential spray rate, MySQL usernames |
| Host Security | Real SSH port auth events, fail2ban bans, targeted usernames |

## Deployment

This repo is deployed from the `honey-net` control plane. Run from the honey-net root:

```
python provision.py --server log-stack
```

After setup completes:
```
Tailscale IP : 100.x.x.x
Grafana      : http://100.x.x.x:3000
Loki         : http://100.x.x.x:3100
```

Run `python sync_ips.py` from honey-net root to capture the Tailscale IP into `state.json`. Honeypot Vector sidecars read it from there.

## Accessing Grafana

Tailscale must be running on your machine.

```
http://<tailscale-ip>:3000
Username: admin
Password: set during setup
```

Useful LogQL queries in Explore:

```logql
{job="cowrie"}   | json | eventid="cowrie.login.failed"   # SSH brute force
{job="mysql"}    | json | event="query"                   # SQL queries
{job="auth"}     |= "Failed"                              # real SSH auth failures
{job="syslog"}   |= "fail2ban"                            # ban/unban events
{job="events"}   | json | event_type="login"              # logins across every honeypot
```

## Re-deploying after changes

```
python redeploy.py --server log-stack   # from honey-net root
```

Rsyncs files from the repo to the server over Tailscale (port 65022), fixes permissions,
and runs `docker compose up -d`. The `.env` is preserved.

## Verifying logs are flowing

```
python test_loki.py   # pushes a test line to Loki, prints the LogQL query to check in Grafana
```

## Repo layout

```
deploy/
  docker-compose.yml
  .env.example
  loki/
    loki-config.yml        # storage, retention (30 days), ingestion limits
  grafana/
    provisioning/
      datasources/         # Loki auto-provisioned as default datasource
      dashboards/          # JSON dashboard definitions (auto-loaded)
  setup/
    setup.sh               # provisioning script
    sshd_hardening.conf
    99-loki-hardening.conf
    fail2ban-jail.local

_lib.py        # shared utilities (reads honey-net.json / state.json from parent repo)
connect.py     # SSH into this server
deploy.py      # copy deploy/ to server
test_loki.py   # push a test log line
```

## Notes

- **Disk:** Loki retention is 30 days. The 25GB Nanode disk is the constraint — monitor with `df -h`. Tune `retention_period` in `loki/loki-config.yml` if needed.
- **Tailscale IP change:** If the server's Tailscale IP changes, update `/opt/log-stack/.env` and run `docker compose down && docker compose up -d`.
- **Locked out by fail2ban:** `fail2ban-client set sshd unbanip <your-ip>` from the Linode LISH console.
