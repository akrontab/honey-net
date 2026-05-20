# server-config — Shared Host Hardening

Configuration applied to every honey-net host at provisioning time. Not a deployable
component on its own — its files are consumed by `deploy.py` when assembling the
deployment package for honeypot servers.

## Files

```
setup.sh              # Base provisioning script (steps 1-9)
sshd_hardening.conf   # Key-only auth, no passwords, minimal options
99-hardening.conf     # sysctl kernel hardening
fail2ban-jail.local   # fail2ban protecting port 65022 (4 retries, 1h ban)
CLAUDE.md             # this file
```

## How deploy.py uses these files

For honeypot servers, `deploy.py`:
1. Copies `sshd_hardening.conf`, `99-hardening.conf`, and `fail2ban-jail.local` to the
   package root alongside `setup.sh`.
2. Assembles `setup.sh` by concatenating `server-config/setup.sh` with each honeypot's
   `setup/fragment.sh`.

The assembled `setup.sh` lands on the server at `/root/<server-name>/setup.sh`. The
conf files are at `/root/<server-name>/sshd_hardening.conf` etc., which is `$SCRIPT_DIR`
from the script's perspective.

Backend servers (`log-stack`) have their own self-contained `setup.sh` and are not
affected by this folder.

## What setup.sh covers (steps 1-9)

1. System update — apt upgrade, install ufw, curl, gnupg, fail2ban, rsync
2. Docker CE — installs docker-compose-plugin, sets custom DNS for containers
3. UFW — opens port 65022 broadly (pre-Tailscale); denies all else. Honeypot ports
   are opened by each honeypot's fragment.sh, not here.
4. sshd — moves to port 65022, drops in `sshd_hardening.conf`, disables socket
   activation (Ubuntu 24.04 quirk), restarts
5. Kernel hardening — copies `99-hardening.conf` to `/etc/sysctl.d/`
6. fail2ban — copies `fail2ban-jail.local` to `/etc/fail2ban/jail.d/`
7. Unattended upgrades — dpkg-reconfigure
8. Deploy files — rsync from `/root/<server>` to `/opt/<server>` (excludes `.env`)
9. Tailscale — installs, joins tailnet, then tightens port 65022 from open-to-all to
   `tailscale0` interface only; writes `.env` for the stack

After step 9, the honeypot's `fragment.sh` adds steps 10+:
opens honeypot ports, creates volume directories, starts the Compose stack.

## Tailscale-restricted SSH

After Tailscale joins, `setup.sh` replaces the broad UFW rule for port 65022 with an
interface-specific rule:

```bash
ufw delete allow 65022/tcp
ufw allow in on tailscale0 to any port 65022 comment 'real SSH — Tailscale only'
```

Port 65022 is invisible to the public internet after this point. fail2ban is kept as
defense-in-depth even though no internet traffic should reach the port.

## Adding a new honeypot

No changes to these files are needed. Create `honey-pots/<name>/deploy/setup/fragment.sh`
with honeypot-specific steps (ports, volumes, stack start). `deploy.py` appends it
automatically.
