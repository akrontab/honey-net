# SMB honeypot fragment — appended to server-config/setup.sh by provision.py.
# Runs after base hardening and Tailscale are in place.
# Opens SMB ports, creates volume directories, and starts the stack.

# ── Open honeypot ports ───────────────────────────────────────────────
echo "[smb] Opening SMB honeypot ports..."
ufw allow "139/tcp" comment 'smb honeypot'
ufw allow "445/tcp" comment 'smb honeypot'

# ── Create volume directories ─────────────────────────────────────────
echo "[smb] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/smb/volumes/logs"
chown honey:honey "${DEPLOY_DIR}/smb/volumes/logs"

# ── Build image and start stack ───────────────────────────────────────
echo "[smb] Building smb honeypot image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build smb"

echo "[smb] Starting stack..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} up -d"

echo ""
echo "================================================================"
echo "  Setup complete: ${SERVER_NAME} (smb component)"
echo ""
echo "  SMB honeypot ports : 139, 445"
echo "  Real SSH port      : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP       : ${TAILSCALE_IP}"
echo ""
echo "  Logs               : ${DEPLOY_DIR}/smb/volumes/logs/smb.json"
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo ""
echo "  Useful commands:"
echo "    DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs -f smb"
echo "    DOCKER_HOST=${HONEY_DOCKER_HOST} docker compose -f ${DEPLOY_DIR}/docker-compose.yml ps"
echo "================================================================"
