# MySQL honeypot fragment — appended to server-config/setup.sh by deploy.ps1.
# Runs after base hardening and Tailscale are in place.
# Adds MySQL-specific UFW port, creates volume directories, and starts the stack.

# ── Create volume directories ─────────────────────────────────────────
echo "[mysql] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/mysql/volumes/logs"
chown honey:honey "${DEPLOY_DIR}/mysql/volumes/logs"

# ── Build mysql image and start combined stack ────────────────────────
# Build explicitly before "up" so malware-sender and mysql-honeypot
# are never built concurrently — concurrent BuildKit builds crash dockerd.
echo "[mysql] Building mysql-honeypot image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build mysql-honeypot"

echo "[mysql] Starting combined honeypot stack..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} up -d"

echo ""
echo "================================================================"
echo "  Setup complete: ${SERVER_NAME}"
echo ""
echo "  MySQL honeypot port : 3306"
echo "  Real SSH port       : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP        : ${TAILSCALE_IP}"
echo ""
echo "  Logs                : ${DEPLOY_DIR}/mysql/volumes/logs/mysql.json"
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo ""
echo "  Useful commands:"
echo "    DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs -f mysql-honeypot"
echo "    DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose -f ${DEPLOY_DIR}/docker-compose.yml ps"
echo "================================================================"
