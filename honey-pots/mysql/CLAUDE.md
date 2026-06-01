# MySQL Honeypot Package

Pure-Python asyncio MySQL wire-protocol honeypot. Implements HandshakeV10 / `mysql_native_password`, accepts all auth, and serves a convincing decoy database (`coinvault_prod`) in response to queries. No real MySQL is involved.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `config.py` | Reads env vars (`LOG_FILE`, `LISTEN_PORT`, `HONEYPOT_HOSTNAME`), creates log dir |
| `logger.py` | `log_event()` — writes JSON events to log file and stdout |
| `decoy.py` | `DECOY_DB` name + `DECOY_DATA` dict — edit to change the fake database |
| `packets.py` | Wire-protocol packet builders. No project imports |
| `query_handler.py` | `QueryHandler` class — owns `current_db`, parses SQL, returns response bytes |
| `protocol.py` | `MySQLHoneypot(asyncio.Protocol)` — connection lifecycle, auth, dispatch |
| `server.py` | Entry point — `asyncio.run(main())` |

`QueryHandler.handle(query, seq)` returns `bytes` directly; the Protocol layer just writes them. Adding queries → edit `query_handler.py`. Changing the decoy → edit `decoy.py`.

## Decoy database — `coinvault_prod`

A fake crypto-exchange DB to keep attackers engaged and reveal tooling/intent. Appears in `SHOW DATABASES` between `mysql` and `performance_schema`.

| Table | Contents |
|---|---|
| `users` | 5 accounts, USD balances up to $14.8 M, bcrypt hashes, TOTP secrets |
| `wallets` | BTC/ETH addresses + balances + `private_key` column |
| `api_keys` | Exchange API keys + secrets with `trade,withdraw` permissions |
| `transactions` | BTC/ETH transactions with realistic tx hashes |
| `withdrawals` | One entry left in `pending` |
| `admin_users` | `superadmin` and `operator` accounts |

All tables visible to `SHOW TABLES`, `DESC`, `SELECT * / COUNT(*) / LIMIT`, and `information_schema` introspection (used by DBeaver/HeidiSQL).

## Logs and events

`/opt/<server>/mysql/volumes/logs/mysql.json` — JSONL, one event per line.

Shipped to Loki as `{job="mysql"}` (raw) and `{job="events", honeypot="mysql"}` (normalised). No binary capture, so no `/samples` mount.

All events include `conn_id` (8-char hex UUID) grouping every event from one TCP connection.

| Event | Key fields |
|---|---|
| `connect` | conn_id, src_ip, src_port |
| `login` | conn_id, username, database |
| `query` | conn_id, username, query (full SQL), database |
| `use_db` | conn_id, username, database |
| `change_user` | conn_id, username |
| `command` | conn_id, cmd (byte), arg (raw) |
| `quit` / `disconnect` | conn_id, username |
| `session` | conn_id, username, database, duration_s, query_count, queries[] |

`session` is emitted on `connection_lost()` just before `disconnect`. Contains the ordered list of queries — the primary event for session-level analysis.

## Normalised event mapping

| MySQL `event` | `event_type` |
|---|---|
| `connect` | `connect` |
| `login` | `login` |
| `query` | `query` |
| `session` | `session_end` |
| (other) | dropped |

`username` and `query` (→ `payload`) are forwarded. `password` is always `null` — `mysql_native_password` uses challenge-response so the plaintext password is never sent. `protocol` is always `"mysql"`. `sample_sha256` is `null`.

### Standard `meta` keys emitted

Vocabulary defined in `honey-pots/CLAUDE.md`. Because MySQL is a built-locally pot, `meta` is minted at the source where cleanest (`logger.py`/`protocol.py`) and the `remap` forwards it:

| `event_type` | `meta` key | Source |
|---|---|---|
| `login` | `login_success` | always `true` — the honeypot accepts every login |
| `login` | `auth_method` | always `"native_password"` |
| `query` (and `login`/`session_end`) | `database` | `raw.database` — `current_db` at event time |

The `query` event now carries `database` (added in `protocol.py`), so the active DB is queryable per statement, not just at login.

## Gotchas

### Never `docker compose up --build` on the combined stack
The top-level compose can include multiple `build:` contexts (mysql-honeypot, malware-sender, cowrie's capture-writer). Concurrent BuildKit crashes dockerd: `"session healthcheck failed fatally: only one connection allowed"`. Build in sequence:
```bash
docker compose build mysql-honeypot
docker compose build malware-sender
docker compose up -d
```
`setup.sh` (via fragments) and `redeploy.py` already do this.

### Port 3306 is very noisy
Internet scanners probe MySQL constantly. Logs grow fast — `df -h /opt/<server>/mysql/volumes`.
