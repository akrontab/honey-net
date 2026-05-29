# server-config — Shared Host Hardening

Configuration applied to every honey-net host at provisioning time. Not deployable on its own — files are consumed by `provision.py` when assembling deployment packages for honeypot servers.

`setup.sh`, `sshd_hardening.conf`, `99-hardening.conf`, and `fail2ban-jail.local` are copied to the package root. `provision.py` then concatenates `server-config/setup.sh` with each honeypot's `setup/fragment.sh` to produce the assembled `setup.sh` that lands on the server.

Backend servers (`log-stack`, `malware-catalog`) have their own self-contained `setup.sh` and are not affected by this folder.

## What setup.sh covers (steps 1–9)

1. **System update** — apt upgrade, install ufw, curl, gnupg, fail2ban, rsync
2. **Docker CE** — installs docker-compose-plugin, sets custom DNS for containers
3. **UFW** — opens 65022 broadly (pre-Tailscale); denies all else. Honeypot ports are opened by each honeypot's `fragment.sh`
4. **sshd** — moves to port 65022, drops in `sshd_hardening.conf`, disables socket activation (Ubuntu 24.04 quirk), restarts
5. **Kernel hardening** — copies `99-hardening.conf` to `/etc/sysctl.d/`
6. **fail2ban** — copies `fail2ban-jail.local` to `/etc/fail2ban/jail.d/`
7. **Unattended upgrades** — dpkg-reconfigure
8. **Deploy files** — rsync from `/root/<server>` to `/opt/<server>` (excludes `.env`); creates `/opt/<server>/inbox/` with `chmod 777` as the shared sample inbox
9. **Tailscale** — installs, joins, then tightens 65022 from open-to-all to `tailscale0` interface only; writes `.env` for the stack

After step 9, each honeypot's `fragment.sh` runs (steps 10+): opens honeypot ports, creates volume directories, and builds images. Whether a fragment starts the Compose stack depends on how it is written — cowrie and metadata fragments do not run `docker compose up -d`; mysql, dionaea, and malware-sender do.

## Shared sample inbox

`/opt/<server>/inbox/` is created here (not in any addon's fragment) for two reasons:

- Honeypots that capture binaries can drop samples even on servers without the metadata/malware-sender addons — they sit unprocessed until addons are added.
- One `chmod 777` lives in one place. Honeypots run as different UIDs (cowrie is 999, others vary); addon containers run as root. A world-writable inbox avoids re-chowning at every fragment.

## Tailscale-restricted SSH

After Tailscale joins, `setup.sh` replaces the broad UFW rule for port 65022 with an interface-specific rule:

```bash
ufw delete allow 65022/tcp
ufw allow in on tailscale0 to any port 65022 comment 'real SSH — Tailscale only'
```

Port 65022 is invisible to the public internet after this point. fail2ban stays as defense-in-depth.
