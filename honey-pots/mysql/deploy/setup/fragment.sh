# MySQL honeypot fragment — appended to server-config/setup.sh by deploy.ps1.
# Runs after base hardening and Tailscale are in place.
# Adds MySQL-specific UFW port, creates volume directories, and starts the stack.

# ── Open honeypot port ────────────────────────────────────────────────
echo "[mysql] Opening MySQL honeypot port 3306..."
ufw allow "3306/tcp" comment 'MySQL honeypot'

# ufw changes can disrupt Docker NAT rules — restart to restore them
systemctl restart docker

# ── Create volume directories ─────────────────────────────────────────
echo "[mysql] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/mysql/volumes/logs"

# ── Start stack ───────────────────────────────────────────────────────
echo "[mysql] Building and starting MySQL honeypot stack..."
cd "${DEPLOY_DIR}"
docker compose up -d --build

echo ""
echo "================================================================"
echo "  Setup complete: ${SERVER_NAME}"
echo ""
echo "  MySQL honeypot port : 3306"
echo "  Real SSH port       : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP        : ${TAILSCALE_IP}"
echo ""
echo "  Logs                : ${DEPLOY_DIR}/mysql/volumes/logs/mysql-honeypot.json"
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo ""
echo "  Useful commands:"
echo "    docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs -f mysql-honeypot"
echo "    docker compose -f ${DEPLOY_DIR}/docker-compose.yml ps"
echo "================================================================"
