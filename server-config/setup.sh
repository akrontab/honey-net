#!/usr/bin/env bash
# Honey-net base host provisioning script.
# Assembled by deploy.ps1: this file is the base, followed by the honeypot's fragment.sh.
# Run as root on a fresh Ubuntu 24.04 LTS Linode Nanode.
#
# What this script covers (steps 1-9):
#   1. Update system packages, install Docker and base tools
#   2. Install Docker CE
#   3. UFW: open port 65022 broadly (before moving sshd — prevents lockout)
#       Honeypot ports are opened by each honeypot's fragment.sh, not here.
#   4. Move real sshd to port 65022 and harden it (key-only auth)
#   5. Apply sysctl kernel hardening
#   6. Configure fail2ban to protect port 65022
#   7. Enable unattended security upgrades
#   8. Deploy project files from /root/$SERVER_NAME to /opt/$SERVER_NAME
#   9. Install Tailscale, join the tailnet, then restrict port 65022 to
#       the Tailscale interface only (tailscale0) — port invisible to public internet
#       Write .env for the stack
#
# The honeypot fragment.sh appended by deploy.ps1 adds steps 10+:
#   opens honeypot ports, creates volume directories, starts the Compose stack.
#
# PREREQUISITE: Verify key-based SSH login works BEFORE running this script.
#   Step 4 disables password auth — you will be locked out if your key is not
#   in ~/.ssh/authorized_keys.

set -euo pipefail

REAL_SSH_PORT=65022
SERVER_NAME="$(basename "$(dirname "$(realpath "$0")")")"
DEPLOY_DIR="/opt/${SERVER_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Run as root (sudo bash setup.sh)" >&2
  exit 1
fi

# ── Collect secrets up front ─────────────────────────────────────────
if [[ -z "${TS_AUTHKEY:-}" ]]; then
  read -rsp "Tailscale auth key (tskey-auth-...): " TS_AUTHKEY
  echo
fi
if [[ -z "${TS_AUTHKEY:-}" ]]; then
  echo "ERROR: Tailscale auth key is required." >&2
  exit 1
fi

if [[ -z "${LOKI_HOST:-}" ]]; then
  read -rp "Loki Tailscale IP (from log-stack setup, leave blank to set later): " LOKI_HOST
fi

if [[ -z "${HONEYPOT_HOSTNAME:-}" ]]; then
  read -rp "Honeypot hostname label [${SERVER_NAME}]: " HONEYPOT_HOSTNAME
  HONEYPOT_HOSTNAME="${HONEYPOT_HOSTNAME:-${SERVER_NAME}}"
fi

echo "================================================================"
echo "  Honey-Net Host Setup: ${SERVER_NAME}"
echo "  Real SSH will move to port ${REAL_SSH_PORT} (Tailscale only after step 9)"
echo "  Reconnect on port ${REAL_SSH_PORT} after this script finishes"
echo "================================================================"
echo ""

# ── 1. System update ────────────────────────────────────────────────
echo "[1/9] Updating system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y -qq ufw curl gnupg ca-certificates fail2ban rsync

# ── 2. Install Docker ────────────────────────────────────────────────
echo "[2/9] Installing Docker..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

systemctl enable --now docker

# Set explicit DNS for containers — without this, apt-get inside containers
# may fail if Docker's default resolver can't reach the internet.
cat > /etc/docker/daemon.json <<'DOCKEREOF'
{"dns": ["8.8.8.8", "1.1.1.1"]}
DOCKEREOF

# ── 3. UFW: open port 65022 before touching sshd ────────────────────
echo "[3/9] Opening real SSH port ${REAL_SSH_PORT} in UFW..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow "${REAL_SSH_PORT}/tcp" comment 'real SSH — Tailscale only after Tailscale joins'
ufw --force enable

# UFW's default FORWARD policy is DROP, which blocks Docker containers from
# routing traffic out (DNS lookups, pip install, apt-get inside build containers).
# Set it to ACCEPT so containers can reach the internet.
sed -i 's/DEFAULT_FORWARD_POLICY="DROP"/DEFAULT_FORWARD_POLICY="ACCEPT"/' /etc/default/ufw
ufw reload

# ufw --force reset wipes Docker's iptables MASQUERADE rule — restart Docker
# so it re-adds its NAT rules, restoring container internet access.
systemctl restart docker

# ── 4. Move sshd to port 65022 ───────────────────────────────────────
echo "[4/9] Moving sshd to port ${REAL_SSH_PORT} and hardening..."
sed -i '/^[[:space:]]*#\?[Pp]ort /d' /etc/ssh/sshd_config
echo "Port ${REAL_SSH_PORT}" >> /etc/ssh/sshd_config

cp "${SCRIPT_DIR}/sshd_hardening.conf" /etc/ssh/sshd_config.d/99-honeypot.conf

# Ubuntu 24.04 uses ssh.socket (systemd socket activation). The socket holds
# the port binding and ignores the Port directive in sshd_config.
# Disable it so the Port directive takes effect.
systemctl stop ssh.socket 2>/dev/null || true
systemctl disable ssh.socket 2>/dev/null || true
systemctl daemon-reload
systemctl restart ssh

echo ""
echo "  >>> sshd is now on port ${REAL_SSH_PORT}. Password auth disabled. <<<"
echo "  >>> Your current session stays open until you close it.           <<<"
echo ""

# ── 5. Sysctl kernel hardening ───────────────────────────────────────
echo "[5/9] Applying sysctl hardening..."
cp "${SCRIPT_DIR}/99-hardening.conf" /etc/sysctl.d/99-hardening.conf
sysctl --system -q

# ── 6. Fail2ban ──────────────────────────────────────────────────────
echo "[6/9] Configuring fail2ban..."
cp "${SCRIPT_DIR}/fail2ban-jail.local" /etc/fail2ban/jail.d/honeypot-host.local
systemctl enable --now fail2ban
systemctl reload fail2ban

# ── 7. Unattended security upgrades ─────────────────────────────────
echo "[7/9] Enabling unattended security upgrades..."
apt-get install -y -qq unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

# ── 8. Deploy project files ──────────────────────────────────────────
echo "[8/9] Deploying files to ${DEPLOY_DIR}..."
mkdir -p "${DEPLOY_DIR}"
rsync -a --exclude='.env' "${SCRIPT_DIR}/" "${DEPLOY_DIR}/"

# ── 9. Tailscale: install, join, restrict SSH port ───────────────────
echo "[9/9] Installing Tailscale and joining tailnet..."
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey="${TS_AUTHKEY}" --hostname="${HONEYPOT_HOSTNAME}" --ssh=false

TAILSCALE_IP=$(tailscale ip -4)
echo "  Tailscale IP: ${TAILSCALE_IP}"

# Tighten port 65022: remove the open-to-all rule, restrict to tailscale0.
# Port 65022 is now invisible to the public internet.
ufw delete allow "${REAL_SSH_PORT}/tcp"
ufw allow in on tailscale0 to any port "${REAL_SSH_PORT}" comment 'real SSH — Tailscale only'

# Write .env for the Compose stack
cat > "${DEPLOY_DIR}/.env" <<EOF
LOKI_HOST=${LOKI_HOST}
HONEYPOT_HOSTNAME=${HONEYPOT_HOSTNAME}
CATALOG_URL=${CATALOG_URL:-}
EOF
chmod 600 "${DEPLOY_DIR}/.env"

if [[ -z "${LOKI_HOST}" ]]; then
  echo ""
  echo "  WARNING: LOKI_HOST is not set. Vector will not ship logs until you"
  echo "  edit ${DEPLOY_DIR}/.env and run: docker compose -f ${DEPLOY_DIR}/docker-compose.yml up -d"
fi

# ── Honeypot fragment continues below ───────────────────────────────
