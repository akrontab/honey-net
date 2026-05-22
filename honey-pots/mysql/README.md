# mysql

MySQL wire-protocol honeypot package for [honey-net](../../README.md). A pure-Python asyncio implementation of the MySQL handshake that accepts all connections, logs credentials and SQL queries, and returns plausible empty result sets. No real MySQL involved.

## What it captures

| Event | Key fields |
|-------|-----------|
| `connect` | src_ip, src_port |
| `login` | username, database |
| `query` | username, full SQL text |
| `use_db` | username, database |
| `change_user` | username |
| `quit` / `disconnect` | username |

Logs are shipped to Loki by Vector with label `{job="mysql"}`.

> **Note:** MySQL native_password authentication is a challenge-response protocol — no cleartext password is transmitted. Only usernames are captured on login.

## Ports

| Port | Protocol | Notes |
|------|----------|-------|
| 3306 | MySQL | Honeypot |
| 65022 | SSH | Real admin access, Tailscale only |

## Layout

```
deploy/
  docker-compose.yml       # mysql-honeypot and vector services
  .env.example
  honeypot/
    Dockerfile             # python:3.12-slim
    server.py              # MySQL wire-protocol emulator (asyncio)
  vector/
    vector.toml            # ships mysql-honeypot.json + host logs to Loki
  setup/
    fragment.sh            # host provisioning steps (appended to server-config/setup.sh)

CLAUDE.md                  # protocol details, event types, known gotchas
test.py                    # smoke test — connects to port 3306 and verifies handshake
```

## How it works

`server.py` implements the MySQL HandshakeV10 packet and `mysql_native_password` auth plugin. The server:

1. Sends a HandshakeV10 greeting with a random auth challenge
2. Reads the client's `HandshakeResponse41` (captures username, database, client flags)
3. Sends `OK` — all auth is accepted
4. Reads and logs any subsequent `COM_QUERY`, `COM_INIT_DB`, `COM_CHANGE_USER`, etc.
5. Returns empty result sets for all queries

This captures automated scanners, credential stuffers, and manual attackers running SQL against what they believe is a live MySQL server.

## Deploying

This package is deployed by the honey-net control plane — not standalone. From the honey-net root:

```
python deploy.py --server <server-name>
python connect.py --server <server-name> --pre-setup
```
```bash
sudo bash /root/<server-name>/setup.sh
```

The image is built locally on the server (not pulled from a registry). `setup.sh` handles this via `docker compose build`.

To push updates to a live server:
```
python redeploy.py --server <server-name>
```

## Testing

From the honey-net root (server must be running):
```
python honey-pots/mysql/test.py
```
Connects to port 3306 and verifies the MySQL handshake packet is received.

## Notes

- **Port 3306 is very noisy.** Internet scanners probe MySQL constantly. Monitor disk usage on the server: `df -h /opt/<server>/mysql/volumes`.
- The image is built locally — never use `docker compose up --build` on the combined stack (concurrent BuildKit builds crash dockerd). `setup.sh` and `redeploy.py` build images sequentially.
