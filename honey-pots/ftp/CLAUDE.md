# FTP Honeypot Package

Pure-Python FTP honeypot using pyftpdlib. Accepts all credentials, presents a
fake financial/crypto filesystem to lure attackers, captures uploaded files
(malware drops), and logs all events as newline-delimited JSON.

## Build approach

`python:3.12-slim` + `pyftpdlib`. Build takes under a minute.

## Ports

| Port | Service |
|------|---------|
| 21 | FTP control channel |
| 60000-60010 | FTP passive data range (PASV) |

Passive mode requires `FTP_PASSIVE_HOST` in the `.env` to be set to the
server's public IP. If unset, passive mode is disabled and only active mode
(PORT) is available.

## Fake filesystem

At startup the honeypot populates `/tmp/ftp-root` with convincing-looking
financial and crypto files:

```
/
├── README.txt
├── accounts/
│   ├── portfolio_2026.csv
│   ├── transactions_Q1_2026.csv
│   └── balance_sheet.txt
├── wallets/
│   ├── ethereum_keystore.json   (V3 keystore format, fake keys)
│   └── seed_phrases_backup.txt  (BIP39-style, fake)
├── exchange/
│   ├── binance_api_keys.txt     (fake API key + secret)
│   └── coinbase_export.csv
└── tax/
    └── crypto_gains_2025.csv
```

All content is plausible in format but entirely fabricated — no real keys,
wallets, or credentials.

## Malware capture

Attackers can upload files via STOR (permissions: `elrwm` — list, retrieve,
store, mkdir; no delete or rename). Uploaded files are:

1. Written to the CWD inside FAKE_ROOT (attacker can retrieve them back).
2. SHA-256 hashed and copied to `/samples/<sha256>` (bind-mounted from
   `/opt/<server>/inbox/ftp/` on the host).
3. A sidecar `/samples/<sha256>.capture.json` is written with provenance
   metadata (`src_ip`, `session_id`, `original_filename`, `captured_at`).

The `metadata` and `malware-sender` addons pick up samples from the shared
`/opt/<server>/inbox/` directory without any FTP-specific configuration.

## Logs

```
/opt/<server>/ftp/volumes/logs/ftp.json   # attacker events (JSONL)
/opt/<server>/inbox/ftp/                  # raw uploads + capture sidecars
```

Shipped to Loki as `{job="ftp"}` (raw) and `{job="events", honeypot="ftp"}`
(normalised).

## Event types

| `type` | Key fields |
|---|---|
| `connection` | `src_host`, `src_port`, `dst_port`, `protocol`, `session_id` |
| `credentials` | `src_host`, `src_port`, `protocol`, `session_id`, `login`, `password` |
| `file_upload` | `src_host`, `src_port`, `protocol`, `session_id`, `username`, `filename`, `size`, `sha256` |
| `file_sent` | `src_host`, `src_port`, `protocol`, `session_id`, `username`, `filename` |
| `session_end` | `src_host`, `src_port`, `protocol`, `session_id`, `username` |

`file_sent` (attacker ran RETR on a fake file) is logged to the raw stream
only — it has no `event_type` equivalent in the normalised schema.

## Normalised event mapping

| `type` | `event_type` | `meta` keys |
|---|---|---|
| `connection` | `connect` | — |
| `credentials` | `login` | `login_success=true`, `auth_method="password"` |
| `file_upload` | `download` | `url=null`, `dl_host=null`, `dl_filename` |
| `session_end` | `session_end` | — |

`password` is **plaintext** — FTP sends credentials in the clear.
`login_success` is always `true` — the honeypot accepts every credential.

## Gotchas

### Passive mode and the public IP
pyftpdlib's PASV response embeds the IP it will listen on. Without
`masquerade_address` set to the server's public IP, clients connecting through
NAT will receive the container's private IP and fail the data connection.

The container auto-detects its public IP at startup by querying `api.ipify.org`
(with `ifconfig.me` as fallback). Set `FTP_PASSIVE_HOST` in `.env` to override
with a static value — useful if outbound HTTP is restricted or the detection
result is wrong.

### Accepts all credentials by design
`HoneypotAuthorizer.validate_authentication` never raises `AuthenticationFailed`.
Attackers see a successful login, which encourages further interaction.

### Paired with smb on smb-ftp
ftp's fragment runs `docker compose up -d` — if smb is listed after ftp,
smb's image may not be built yet and docker compose will auto-build it
inline. smb's fragment then runs `up -d` again as a no-op.
