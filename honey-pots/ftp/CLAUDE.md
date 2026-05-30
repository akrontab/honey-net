# FTP Honeypot Package

Pure-Python FTP honeypot using pyftpdlib. Accepts all credentials
(so attackers believe they're in and reveal more intent), logs connection
and authentication events as newline-delimited JSON.

## Build approach

`python:3.12-slim` + `pyftpdlib`. Build takes under a minute.

## Ports

| Port | Service |
|------|---------|
| 21   | FTP control channel |

Passive mode is disabled — only the control channel is exposed.
Credential capture on port 21 is sufficient; passive data connections
are not needed for a honeypot.

## Logs

```
/opt/<server>/ftp/volumes/logs/ftp.json   # attacker events (JSONL)
```

Shipped to Loki as `{job="ftp"}` (raw) and `{job="events", honeypot="ftp"}` (normalised).

## Event types

| `type` | Key fields |
|---|---|
| `connection` | `src_host`, `src_port`, `dst_port`, `protocol` |
| `credentials` | `src_host`, `src_port`, `protocol`, `login`, `password` |

## Normalised event mapping

| `type` | `event_type` |
|---|---|
| `connection` | `connect` |
| `credentials` | `login` |

`password` is **plaintext** — FTP sends credentials in the clear and the
honeypot accepts everything, so every password attempt is captured.
`session_id` and `sample_sha256` are always null.

## Gotchas

### Accepts all credentials by design
`HoneypotAuthorizer.validate_authentication` never raises `AuthenticationFailed`.
Attackers see a successful login, which encourages further interaction.

### Paired with smb on smb-ftp
ftp's fragment runs `docker compose up -d` — if smb is listed after ftp,
smb's image may not be built yet and docker compose will auto-build it
inline. smb's fragment then runs `up -d` again as a no-op.
