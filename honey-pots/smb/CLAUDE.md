# SMB Honeypot Package

Captures SMB/CIFS authentication attempts on ports 139 and 445 using
impacket's `SimpleSMBServer`. Logs NTLM credentials and connection events
as newline-delimited JSON.

## Build approach

Pure Python — `python:3.12-slim` base with a single dependency (`impacket`).
Build takes under a minute. No compilation required.

## Ports

| Port | Service |
|------|---------|
| 139  | NetBIOS over TCP |
| 445  | SMB/CIFS |

## Logs

```
/opt/<server>/smb/volumes/logs/smb.json   # attacker events (JSONL)
```

Shipped to Loki as `{job="smb"}` (raw) and `{job="events", honeypot="smb"}` (normalised).

## Event types in smb.json

| `type` | Key fields |
|---|---|
| `connection` | `src_host`, `src_port`, `dst_port`, `protocol` |
| `credentials` | `protocol`, `login`, `password` |

## Normalised event mapping

| `type` | `event_type` |
|---|---|
| `connection` | `connect` |
| `credentials` | `login` |

`login` is `DOMAIN\user` when a domain is present, else just `user`.

`password` contains the full NTLMv2 hash string (hashcat-ready format:
`user::domain:ServerChallenge:NTProofStr:blob`) when the hash line is
captured, or `null` when only the username was extracted from the
AUTHENTICATE_MESSAGE log line.

`session_id` and `sample_sha256` are always null.

## Gotchas

### Paired with dionaea on smb-ftp
dionaea handles FTP (port 21); this package handles SMB (ports 139, 445).
The smb fragment runs `docker compose up -d` as the terminal step for the
combined stack. If smb is removed from the server, run `up -d` manually or
add another terminal component.

### Credential parser depends on impacket log format
`smb_honeypot.py` parses impacket's internal log messages using regexes.
If impacket changes its log format in a future release, update `_RE_CONNECT`,
`_RE_AUTH`, and `_RE_HASH` in `smb_honeypot.py`.

### NTLMv2 hashes, not plaintext
SMB authentication uses NTLM challenge-response. Captured passwords are
NTLMv2 hashes, not cleartext. Crack offline with:
```
hashcat -m 5600 hash.txt wordlist.txt
```
