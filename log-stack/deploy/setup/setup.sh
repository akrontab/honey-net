#!/usr/bin/env bash
# Log-stack host provisioning script (Grafana + Loki + Tailscale)
# Run as root on a fresh Ubuntu 24.04 LTS server.
#
# What this does:
#   1. Updates the system and installs Docker + fail2ban
#   2. Opens port 65022 in UFW before moving sshd
#   3. Moves real sshd to port 65022 and hardens it (key-only auth)
#   4. Locks down UFW (65022 for SSH, everything else denied)
#   5. Applies sysctl kernel hardening
#   6. Configures fail2ban to protect port 65022
#   7. Enables unattended security upgrades
#   8. Installs Tailscale and joins the tailnet
#   9. Writes .env (Tailscale IP + Grafana password) and starts the stack
#
# PREREQUISITE: Verify that key-based SSH login works on port 65022 BEFORE
# running this script. Step 3 disables password auth — you will be locked out
# if your key is not in ~/.ssh/authorized_keys on the VM.

set -euo pipefail

REAL_SSH_PORT=65022
DEPLOY_DIR="/opt/log-stack"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Run as root (sudo bash setup.sh)" >&2
  exit 1
fi

# ── Re-deploy mode: sync files and restart stack, skip full provisioning ──
if [[ "${1:-}" == "--redeploy" ]]; then
  echo "Syncing files to ${DEPLOY_DIR}..."
  cp -r "${SCRIPT_DIR}/../." "${DEPLOY_DIR}/"
  chown -R honey:honey "${DEPLOY_DIR}"
  chmod -R a+rX "${DEPLOY_DIR}"
  HONEY_UID=$(id -u honey)
  HONEY_DOCKER_HOST="unix:///run/user/${HONEY_UID}/docker.sock"
  HONEY_DC="XDG_RUNTIME_DIR=/run/user/${HONEY_UID} DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose"
  su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} up -d"
  su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} restart grafana"
  echo "Done."
  exit 0
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

if [[ -z "${GRAFANA_PASSWORD:-}" ]]; then
  read -rsp "Grafana admin password: " GRAFANA_PASSWORD
  echo
fi
if [[ -z "${GRAFANA_PASSWORD:-}" ]]; then
  echo "ERROR: Grafana admin password is required." >&2
  exit 1
fi

echo "================================================================"
echo "  Log-Stack Setup (Grafana + Loki)"
echo "  Real SSH will move to port ${REAL_SSH_PORT}"
echo "  Reconnect on port ${REAL_SSH_PORT} after this script finishes"
echo "================================================================"
echo ""

# ── 1. System update ────────────────────────────────────────────────
echo "[1/9] Updating system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y -qq ufw curl gnupg ca-certificates fail2ban uidmap

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
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-ce-rootless-extras

systemctl enable --now docker

# DNS for root's dockerd.
cat > /etc/docker/daemon.json <<'EOF'
{"dns": ["8.8.8.8", "1.1.1.1"]}
EOF

# Create non-root service user — no docker group; runs Docker stacks via rootless dockerd.
# No SSH access (AllowUsers root in sshd config) — only reachable via su.
id honey &>/dev/null || useradd -m -s /bin/bash honey

# Allocate subordinate UID/GID ranges for honey's user namespaces (rootless Docker requirement).
grep -q "^honey:" /etc/subuid || echo "honey:100000:65536" >> /etc/subuid
grep -q "^honey:" /etc/subgid || echo "honey:100000:65536" >> /etc/subgid

HONEY_UID=$(id -u honey)
HONEY_DOCKER_HOST="unix:///run/user/${HONEY_UID}/docker.sock"
HONEY_DC="XDG_RUNTIME_DIR=/run/user/${HONEY_UID} DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose"

# DNS for honey's rootless dockerd.
mkdir -p /home/honey/.config/docker
cat > /home/honey/.config/docker/daemon.json <<'EOF'
{"dns": ["8.8.8.8", "1.1.1.1"]}
EOF
chown -R honey:honey /home/honey/.config

loginctl enable-linger honey

timeout 15 bash -c "until [[ -S /run/user/${HONEY_UID}/bus ]]; do sleep 0.5; done" || {
  echo "ERROR: honey user session bus not ready — is systemd-logind running?" >&2; exit 1
}

su -s /bin/bash honey -c "
  export XDG_RUNTIME_DIR=/run/user/${HONEY_UID}
  export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${HONEY_UID}/bus
  export HOME=/home/honey
  dockerd-rootless-setuptool.sh install --force
  systemctl --user enable docker
  systemctl --user start docker
"

timeout 30 bash -c "until su -s /bin/bash honey -c \
  'XDG_RUNTIME_DIR=/run/user/${HONEY_UID} DOCKER_HOST=${HONEY_DOCKER_HOST} docker info >/dev/null 2>&1'; \
  do sleep 1; done" || {
  echo "ERROR: rootless dockerd did not start in time" >&2; exit 1
}
echo "  Rootless dockerd ready (uid=${HONEY_UID}, socket=${HONEY_DOCKER_HOST})"

# ── 3. UFW — open real SSH port before touching sshd ────────────────
echo "[3/9] Configuring UFW..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow "${REAL_SSH_PORT}/tcp" comment 'real SSH'
# Ports 3000 (Grafana) and 3100 (Loki) are NOT opened here.
# They bind to the Tailscale IP only and are unreachable from the public internet.
ufw --force enable

# ufw --force reset wipes Docker's iptables MASQUERADE rule — restart Docker
# so it re-adds its NAT rules on top of UFW's, restoring container internet access.
systemctl restart docker

# ── 4. Move sshd to port 65022 ───────────────────────────────────────
echo "[4/9] Moving sshd to port ${REAL_SSH_PORT} and hardening..."
sed -i '/^[[:space:]]*#\?[Pp]ort /d' /etc/ssh/sshd_config
echo "Port ${REAL_SSH_PORT}" >> /etc/ssh/sshd_config
cp "${SCRIPT_DIR}/sshd_hardening.conf" /etc/ssh/sshd_config.d/99-log-stack.conf

# Ubuntu 24.04 uses socket activation — ssh.socket holds the port binding and
# overrides sshd_config. Disable it so the Port directive in sshd_config takes effect.
systemctl stop ssh.socket 2>/dev/null || true
systemctl disable ssh.socket 2>/dev/null || true
systemctl daemon-reload
systemctl restart ssh

echo ""
echo "  >>> sshd is now on port ${REAL_SSH_PORT}. Password auth disabled. <<<"
echo ""

# ── 5. Kernel hardening ──────────────────────────────────────────────
echo "[5/9] Applying sysctl hardening..."
cp "${SCRIPT_DIR}/99-loki-hardening.conf" /etc/sysctl.d/99-loki-hardening.conf
sysctl --system -q

# ── 6. Fail2ban ──────────────────────────────────────────────────────
echo "[6/9] Configuring fail2ban..."
cp "${SCRIPT_DIR}/fail2ban-jail.local" /etc/fail2ban/jail.d/log-stack-host.local
systemctl enable --now fail2ban
systemctl reload fail2ban

# ── 7. Unattended upgrades ───────────────────────────────────────────
echo "[7/9] Enabling unattended security upgrades..."
apt-get install -y -qq unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

# ── 8. Tailscale ─────────────────────────────────────────────────────
echo "[8/9] Installing and joining Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey="${TS_AUTHKEY}" --hostname="log-stack" --ssh=false

TAILSCALE_IP=$(tailscale ip -4)
echo "  Tailscale IP: ${TAILSCALE_IP}"

# ── 9. Deploy and start stack ─────────────────────────────────────────
echo "[9/9] Deploying to ${DEPLOY_DIR} and starting stack..."
mkdir -p "${DEPLOY_DIR}"
cp -r "${SCRIPT_DIR}/../." "${DEPLOY_DIR}/"
# Grafana runs as uid 472 — ensure it can read provisioning files
chown -R honey:honey "${DEPLOY_DIR}"
chmod -R a+rX "${DEPLOY_DIR}"

cat > "${DEPLOY_DIR}/.env" <<EOF
TAILSCALE_IP=${TAILSCALE_IP}
GRAFANA_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
EOF
chown honey:honey "${DEPLOY_DIR}/.env"
chmod 600 "${DEPLOY_DIR}/.env"

su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} pull"
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} up -d"

echo ""
echo "================================================================"
echo "  Setup complete."
echo ""
echo "  Real SSH port   : ${REAL_SSH_PORT}"
echo "  Tailscale IP    : ${TAILSCALE_IP}"
echo "  Grafana         : http://${TAILSCALE_IP}:3000  (Tailscale only)"
echo "  Loki            : http://${TAILSCALE_IP}:3100  (Tailscale only)"
echo ""
echo "  Useful commands:"
echo "    DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs -f"
echo "    DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose -f ${DEPLOY_DIR}/docker-compose.yml ps"
echo ""
echo "  Next: add the Cowrie host to Tailscale and configure Vector"
echo "  to ship logs to http://${TAILSCALE_IP}:3100"
echo "================================================================"
