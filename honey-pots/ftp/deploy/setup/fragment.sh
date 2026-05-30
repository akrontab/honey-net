# FTP honeypot fragment — appended to server-config/setup.sh by provision.py.
# Runs after base hardening and Tailscale are in place.

# ── Open honeypot port ────────────────────────────────────────────────
echo "[ftp] Opening FTP honeypot port..."
ufw allow "21/tcp" comment 'ftp honeypot'

# ── Create volume directories ─────────────────────────────────────────
echo "[ftp] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/ftp/volumes/logs"
chown honey:honey "${DEPLOY_DIR}/ftp/volumes/logs"

# ── Build image and start stack ───────────────────────────────────────
echo "[ftp] Building ftp honeypot image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build ftp"

echo "[ftp] Starting stack..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} up -d"

echo ""
echo "================================================================"
echo "  Setup complete: ${SERVER_NAME} (ftp component)"
echo ""
echo "  FTP honeypot port  : 21"
echo "  Real SSH port      : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP       : ${TAILSCALE_IP}"
echo ""
echo "  Logs               : ${DEPLOY_DIR}/ftp/volumes/logs/ftp.json"
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo "================================================================"
