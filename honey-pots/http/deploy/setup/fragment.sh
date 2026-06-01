# HTTP honeypot fragment — appended to server-config/setup.sh by provision.py.
# Runs after base hardening and Tailscale are in place.
# Build-only: a later component's fragment runs `docker compose up -d`
# (on mysql-ssh the terminal addon is malware-sender). Keep `http` ahead of a
# component that starts the stack, or this pot is built but never started.

# ── Open honeypot port ────────────────────────────────────────────────
echo "[http] Opening HTTP honeypot port 80..."
ufw allow "80/tcp" comment 'http honeypot'

# ── Create volume directories ─────────────────────────────────────────
echo "[http] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/http/volumes/logs"
chown honey:honey "${DEPLOY_DIR}/http/volumes/logs"

# Per-honeypot inbox subdir — server-config created the parent inbox/ with 777.
mkdir -p "${DEPLOY_DIR}/inbox/http"
chmod 777 "${DEPLOY_DIR}/inbox/http"

# ── Build image (a later fragment starts the stack) ───────────────────
echo "[http] Building http honeypot image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build http"

echo "[http] HTTP configured — stack will start after all addons are set up."
