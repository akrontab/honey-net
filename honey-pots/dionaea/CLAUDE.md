# Dionaea Honeypot Package

Multi-protocol honeypot capturing SMB/CIFS and FTP. Built from source — the upstream `dinotools/dionaea:latest` image crashes with SIGTRAP (exit 133) on any modern kernel.

## Build approach

`deploy/dionaea/Dockerfile` clones upstream and compiles against Ubuntu 22.04. Two subdirectories are bind-mounted over the installed defaults:

- `services-enabled/` — only SMB + FTP start (drop everything else)
- `ihandlers-enabled/` — only JSON logging is active

The `emu` module (x86 shellcode detection) is disabled at build time (`-DWITH_MODULE_EMU=OFF`) because `libemu-dev` is not in Ubuntu 22.04 repos. No impact on credential/file capture.

**First build takes ~15 min on a Nanode.** Cached in Docker's layer cache; `redeploy.py` only rebuilds if the Dockerfile changes.

## Ports

| Port | Service |
|------|---------|
| 21 | FTP |
| 139 | SMB/NetBIOS |
| 445 | SMB/CIFS |

## Logs and samples

```
/opt/<server>/dionaea/volumes/logs/dionaea.json   # attacker events (JSONL)
/opt/<server>/dionaea/volumes/logs/dionaea.log    # application log (text)
/opt/<server>/inbox/dionaea/                      # captured binaries (md5-named)
```

Dionaea's internal binary path (`/opt/dionaea/var/lib/dionaea/binaries/`) is bind-mounted to the shared inbox. The `metadata` addon canonicalises md5-named binaries to `<sha256>`.

Shipped to Loki as `{job="dionaea"}` (raw) and `{job="events", honeypot="dionaea"}` (normalised).

## Event types in dionaea.json

| `type` | Key fields |
|---|---|
| `connection` | `src_host`, `src_port`, `dst_port`, `protocol` |
| `credentials` | `src_host`, `protocol`, `login`, `password` |
| `download` | `src_host`, `protocol`, `url`, `md5hash`, `sha512hash`, `filelocation` |

## Normalised event mapping

| dionaea `type` | `event_type` |
|---|---|
| `connection` | `connect` |
| `credentials` | `login` |
| `download` | `download` |

`login`/`password` → `username`/`password`. On downloads `payload` is `null` and the URL lives in `meta.url`. `sample_sha256` is **null** (dionaea reports md5/sha512 but not sha256 — pivot via the canonical sidecar at `/opt/<server>/inbox/<sha256>.meta.json`). `session_id` is null (dionaea has no per-connection ID).

### Standard `meta` keys emitted

Vocabulary defined in `honey-pots/CLAUDE.md`. Dionaea's `remap` derives, on `download` events:

| `meta` key | Derived from |
|---|---|
| `url` | `raw.url` |
| `dl_host` | host of `raw.url` (`parse_url`; skipped if the URL isn't parseable, e.g. SMB paths) |
| `dl_filename` | last path segment of `raw.url` |

## Provenance limitation

Dionaea has **no capture-sidecar writer**, unlike cowrie. Upstream code can't easily be patched to emit `<binary>.capture.json` at capture time. The canonical sidecar (from the metadata addon) gets `honeypot: "dionaea"` and `original_name`, but `src_ip` / `url` / `session_id` are `null`.

To recover provenance: pivot through `{job="dionaea"}` on `md5hash`. If this becomes painful, the next step is a log-tailing sidecar or a catalog-side join on the dionaea log stream.

## Gotchas

### SIGSEGV (exit 139) on kernel 6.8+ — libnetfilter-queue and libpcap removed
Dionaea crashes immediately on modern kernels (6.8+) when the nfqhook or pcap modules
are compiled in. The Dockerfile omits `libnetfilter-queue-dev` and `libpcap-dev` so those
modules are skipped at cmake time. `seccomp=unconfined` is also set as defence-in-depth
but the module omission is the real fix.

### Port 445 conflicts
Ubuntu 24.04 should not bind 445 by default but verify: `ss -tlnp | grep 445`.

### FTP passive mode is not configured
Only port 21 (control channel) is exposed; passive data connections fail. Intentional — credential capture on the control channel is sufficient.

### SMB is very noisy
Constant automated probes; logs grow quickly. `df -h /opt/<server>/dionaea/volumes`.
