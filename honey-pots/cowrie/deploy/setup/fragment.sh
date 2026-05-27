# Cowrie honeypot fragment — appended to server-config/setup.sh by deploy.ps1.
# Runs after base hardening and Tailscale are in place.
# Adds cowrie-specific UFW ports, creates volume directories, and starts the stack.

# ── Open honeypot ports ───────────────────────────────────────────────
echo "[cowrie] Opening honeypot ports 22 and 23..."
ufw allow "22/tcp"  comment 'cowrie SSH honeypot'
ufw allow "23/tcp"  comment 'cowrie Telnet honeypot'

# ── Create volume directories ─────────────────────────────────────────
echo "[cowrie] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/var/log/cowrie"
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/var/lib/cowrie"
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/logs"

# Per-honeypot inbox subdir — server-config created the parent inbox/ with 777.
mkdir -p "${DEPLOY_DIR}/inbox/cowrie"
chmod 777 "${DEPLOY_DIR}/inbox/cowrie"

# Cowrie runs as UID 999 inside the container — volumes must be owned by it.
# Config files must be world-readable so the in-container user can traverse them.
find "${DEPLOY_DIR}/cowrie/cowrie" -type d -exec chmod 755 {} \;
find "${DEPLOY_DIR}/cowrie/cowrie" -type f -exec chmod 644 {} \;
chown -R 999:999 "${DEPLOY_DIR}/cowrie/volumes"

# ── Pre-fetch images and build capture-writer ─────────────────────────
echo "[cowrie] Pre-fetching images..."
cd "${DEPLOY_DIR}"
docker compose pull cowrie

echo "[cowrie] Building capture-writer image..."
docker compose build capture-writer

echo "[cowrie] Cowrie configured — stack will start after all addons are set up."
