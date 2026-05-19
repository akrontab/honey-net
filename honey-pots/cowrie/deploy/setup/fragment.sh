# Cowrie honeypot fragment — appended to server-config/setup.sh by deploy.ps1.
# Runs after base hardening and Tailscale are in place.
# Adds cowrie-specific UFW ports, creates volume directories, and starts the stack.

# ── Open honeypot ports ───────────────────────────────────────────────
echo "[cowrie] Opening honeypot ports 22 and 23..."
ufw allow "22/tcp"  comment 'cowrie SSH honeypot'
ufw allow "23/tcp"  comment 'cowrie Telnet honeypot'

# ufw changes can disrupt Docker NAT rules — restart to restore them
systemctl restart docker

# ── Create volume directories ─────────────────────────────────────────
echo "[cowrie] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/var/log/cowrie"
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/var/lib/cowrie/downloads"

# Cowrie runs as UID 999 inside the container — volumes must be owned by it.
# Config files must be world-readable so the in-container user can traverse them.
find "${DEPLOY_DIR}/cowrie/cowrie" -type d -exec chmod 755 {} \;
find "${DEPLOY_DIR}/cowrie/cowrie" -type f -exec chmod 644 {} \;
chown -R 999:999 "${DEPLOY_DIR}/cowrie/volumes"

# ── Start stack ───────────────────────────────────────────────────────
echo "[cowrie] Starting Cowrie stack..."
cd "${DEPLOY_DIR}"
docker compose pull
docker compose up -d

echo ""
echo "================================================================"
echo "  Setup complete: ${SERVER_NAME}"
echo ""
echo "  Cowrie SSH port    : 22"
echo "  Cowrie Telnet port : 23"
echo "  Real SSH port      : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP       : ${TAILSCALE_IP}"
echo ""
echo "  Logs               : ${DEPLOY_DIR}/cowrie/volumes/var/log/cowrie/cowrie.json"
echo "  Malware samples    : ${DEPLOY_DIR}/cowrie/volumes/var/lib/cowrie/downloads/"
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo ""
echo "  Useful commands:"
echo "    docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs -f cowrie"
echo "    docker compose -f ${DEPLOY_DIR}/docker-compose.yml ps"
echo "================================================================"
