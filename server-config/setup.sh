#!/usr/bin/env bash
# Honey-net honeypot host provisioning — base function library.
#
# This file defines functions only; lib/package.py appends a generated tail
# containing configure_ports(), reconcile_ports(), fragment_<name>() functions,
# and the HONEYNET_PHASE dispatcher (firstboot | reconfigure).
#
# HONEYNET_PHASE=firstboot (default)
#   Runs all first-boot steps: apt/Docker install, UFW bootstrap, SSH port move,
#   idempotent config, file deploy, Tailscale join, honeypot fragment setup.
#
# HONEYNET_PHASE=reconfigure
#   Re-applies only the idempotent config steps on an already-provisioned box
#   over Tailscale :65022.  Never moves SSH, never joins Tailscale again.

set -euo pipefail

REAL_SSH_PORT=65022
SERVER_NAME="$(basename "$(dirname "$(realpath "$0")")")"
DEPLOY_DIR="/opt/${SERVER_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Run as root (sudo bash setup.sh)" >&2
  exit 1
fi

# ── First-boot-only functions ─────────────────────────────────────────────────

firstboot_secrets() {
  # Collect required env vars interactively if not already set by the caller.
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
}

firstboot_apt() {
  echo "[1/9] Updating system packages..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
  apt-get install -y -qq ufw curl gnupg ca-certificates fail2ban rsync uidmap passt
}

firstboot_docker() {
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

  # DNS for root's dockerd — used by any admin containers run as root.
  cat > /etc/docker/daemon.json <<'DOCKEREOF'
{"dns": ["8.8.8.8", "1.1.1.1"]}
DOCKEREOF

  # Create non-root service user — no docker group; runs Docker stacks via rootless dockerd.
  # No SSH access (AllowUsers root in sshd config) — only reachable via su.
  id honey &>/dev/null || useradd -m -s /bin/bash honey

  # adm group: read-only access to /var/log files (auth.log, syslog).
  usermod -aG adm honey

  # Allocate subordinate UID/GID ranges for honey's user namespaces (rootless Docker requirement).
  grep -q "^honey:" /etc/subuid || echo "honey:100000:65536" >> /etc/subuid
  grep -q "^honey:" /etc/subgid || echo "honey:100000:65536" >> /etc/subgid

  # Set globals used by fragment functions.
  HONEY_UID=$(id -u honey)
  HONEY_DOCKER_HOST="unix:///run/user/${HONEY_UID}/docker.sock"
  HONEY_DC="XDG_RUNTIME_DIR=/run/user/${HONEY_UID} DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose"
  HONEY_SUBUID_START=$(awk -F: -v user=honey '$1==user{print $2}' /etc/subuid)

  # DNS for honey's rootless dockerd (mirrors /etc/docker/daemon.json for root's daemon).
  mkdir -p /home/honey/.config/docker
  cat > /home/honey/.config/docker/daemon.json <<'DOCKEREOF'
{"dns": ["8.8.8.8", "1.1.1.1"]}
DOCKEREOF

  # Switch rootless Docker's network driver from slirp4netns to pasta.
  # slirp4netns blocks inbound connections on ports 139 and 445 (SMB) as an
  # anti-worm measure — pasta does not have this restriction.
  mkdir -p /home/honey/.config/systemd/user/docker.service.d
  cat > /home/honey/.config/systemd/user/docker.service.d/pasta.conf <<'PASTAEOF'
[Service]
Environment=DOCKERD_ROOTLESS_ROOTLESSKIT_NET=pasta
# Port driver intentionally left unset: dockerd-rootless.sh defaults to "implicit" when
# net=pasta, which auto-detects ports bound in the namespace and preserves source IPs.
PASTAEOF

  chown -R honey:honey /home/honey/.config

  # Persistent user slice: systemd keeps honey's session alive across reboots without a login.
  loginctl enable-linger honey

  # Wait for systemd-logind to create the XDG runtime dir and start the user D-Bus socket.
  timeout 15 bash -c "until [[ -S /run/user/${HONEY_UID}/bus ]]; do sleep 0.5; done" || {
    echo "ERROR: honey user session bus not ready — is systemd-logind running?" >&2; exit 1
  }

  # Install rootless dockerd and start it under honey's user session.
  su -s /bin/bash honey -c "
    export XDG_RUNTIME_DIR=/run/user/${HONEY_UID}
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${HONEY_UID}/bus
    export HOME=/home/honey
    dockerd-rootless-setuptool.sh install --force
    systemctl --user enable docker
    systemctl --user start docker
  "

  # Verify the daemon is accepting connections before proceeding.
  timeout 30 bash -c "until su -s /bin/bash honey -c \
    'XDG_RUNTIME_DIR=/run/user/${HONEY_UID} DOCKER_HOST=${HONEY_DOCKER_HOST} docker info >/dev/null 2>&1'; \
    do sleep 1; done" || {
    echo "ERROR: rootless dockerd did not start in time" >&2; exit 1
  }
  echo "  Rootless dockerd ready (uid=${HONEY_UID}, socket=${HONEY_DOCKER_HOST})"
}

ufw_bootstrap() {
  echo "[3/9] Opening real SSH port ${REAL_SSH_PORT} in UFW..."
  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow "${REAL_SSH_PORT}/tcp" comment 'real SSH — Tailscale only after Tailscale joins'
  ufw --force enable

  # UFW's default FORWARD policy is DROP, which blocks Docker containers from routing
  # traffic out (DNS lookups, pip install, apt-get inside build containers).
  sed -i 's/DEFAULT_FORWARD_POLICY="DROP"/DEFAULT_FORWARD_POLICY="ACCEPT"/' /etc/default/ufw
  ufw reload

  # ufw --force reset wipes Docker's iptables MASQUERADE rule — restart Docker so it
  # re-adds its NAT rules, restoring container internet access.
  systemctl restart docker
}

sshd_move() {
  echo "[4/9] Moving sshd to port ${REAL_SSH_PORT}..."
  sed -i '/^[[:space:]]*#\?[Pp]ort /d' /etc/ssh/sshd_config
  echo "Port ${REAL_SSH_PORT}" >> /etc/ssh/sshd_config

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
}

unattended() {
  echo "[7/9] Enabling unattended security upgrades..."
  apt-get install -y -qq unattended-upgrades
  dpkg-reconfigure -f noninteractive unattended-upgrades
}

deploy_files() {
  echo "[8/9] Deploying files to ${DEPLOY_DIR}..."
  mkdir -p "${DEPLOY_DIR}"
  rsync -a --exclude='.env' "${SCRIPT_DIR}/" "${DEPLOY_DIR}/"

  # Shared sample inbox — created here so honeypots can drop binaries into
  # /opt/<server>/inbox/<honeypot>/ even on servers without the metadata addon.
  mkdir -p "${DEPLOY_DIR}/inbox"
  chmod 777 "${DEPLOY_DIR}/inbox"

  # Transfer ownership to honey so Docker/Compose runs as non-root.
  chown -R honey:honey "${DEPLOY_DIR}"
}

tailscale_join() {
  echo "[9/9] Installing Tailscale and joining tailnet..."
  curl -fsSL https://tailscale.com/install.sh | sh
  tailscale up --authkey="${TS_AUTHKEY}" --hostname="${HONEYPOT_HOSTNAME}" --ssh=false

  TAILSCALE_IP=$(tailscale ip -4)
  echo "  Tailscale IP: ${TAILSCALE_IP}"

  # Tighten port 65022: remove the open-to-all rule, restrict to tailscale0.
  ufw delete allow "${REAL_SSH_PORT}/tcp"
  ufw allow in on tailscale0 to any port "${REAL_SSH_PORT}" comment 'real SSH — Tailscale only'

  # Restart Docker to restore its NAT/MASQUERADE iptables rules after Tailscale
  # joined and UFW rules were modified.
  systemctl restart docker
}

write_env() {
  cat > "${DEPLOY_DIR}/.env" <<EOF
LOKI_HOST=${LOKI_HOST}
HONEYPOT_HOSTNAME=${HONEYPOT_HOSTNAME}
CATALOG_URL=${CATALOG_URL:-}
EOF
  chown honey:honey "${DEPLOY_DIR}/.env"
  chmod 600 "${DEPLOY_DIR}/.env"

  if [[ -z "${LOKI_HOST}" ]]; then
    echo ""
    echo "  WARNING: LOKI_HOST is not set. Vector will not ship logs until you"
    echo "  edit ${DEPLOY_DIR}/.env and run: docker compose -f ${DEPLOY_DIR}/docker-compose.yml up -d"
  fi
}

# ── Idempotent config functions (safe to re-run on a live box) ────────────────

configure_sshd() {
  echo "[sshd] Applying SSH hardening config..."
  cp "${SCRIPT_DIR}/sshd_hardening.conf" /etc/ssh/sshd_config.d/99-honeypot.conf
  sshd -t
  systemctl reload ssh
}

configure_sysctl() {
  echo "[sysctl] Applying kernel hardening..."
  cp "${SCRIPT_DIR}/99-hardening.conf" /etc/sysctl.d/99-hardening.conf
  sysctl --system -q
}

configure_fail2ban() {
  echo "[fail2ban] Configuring fail2ban..."
  cp "${SCRIPT_DIR}/fail2ban-jail.local" /etc/fail2ban/jail.d/honeypot-host.local
  systemctl enable --now fail2ban
  systemctl reload fail2ban
}

# configure_ports(), reconcile_ports(), fragment_<name>() and the phase dispatcher
# are appended by lib/package.py — do not add code below this line.
