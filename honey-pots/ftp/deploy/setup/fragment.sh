# FTP honeypot fragment — appended to server-config/setup.sh by provision.py.
# Runs after base hardening and Tailscale are in place.

# ── Create volume directories ─────────────────────────────────────────
echo "[ftp] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/ftp/volumes/logs"
chown honey:honey "${DEPLOY_DIR}/ftp/volumes/logs"

# Per-honeypot inbox for uploaded malware samples.
mkdir -p "${DEPLOY_DIR}/inbox/ftp"
chmod 777 "${DEPLOY_DIR}/inbox/ftp"

# ── UFW rules ─────────────────────────────────────────────────────────
echo "[ftp] Opening firewall ports..."
ufw allow 21/tcp comment "FTP control"
ufw allow 60000:60010/tcp comment "FTP passive data"

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
echo "  FTP passive ports  : 60000-60010"
echo "  Real SSH port      : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP       : ${TAILSCALE_IP}"
echo ""
echo "  Logs               : ${DEPLOY_DIR}/ftp/volumes/logs/ftp.json"
echo "  Sample inbox       : ${DEPLOY_DIR}/inbox/ftp/"
echo ""
echo "  NOTE: Set FTP_PASSIVE_HOST in ${DEPLOY_DIR}/ftp/.env to enable"
echo "        passive mode (set to the server's public IP)."
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo "================================================================"
