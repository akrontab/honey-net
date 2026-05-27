# Dionaea honeypot fragment — appended to server-config/setup.sh by deploy.py.
# Runs after base hardening and Tailscale are in place.
# Opens SMB and FTP ports, creates volume directories, and starts the stack.

# ── Open honeypot ports ───────────────────────────────────────────────
echo "[dionaea] Opening SMB and FTP honeypot ports..."
ufw allow "21/tcp"  comment 'dionaea FTP honeypot'
ufw allow "139/tcp" comment 'dionaea SMB honeypot'
ufw allow "445/tcp" comment 'dionaea SMB honeypot'

# ── Create volume directories ─────────────────────────────────────────
echo "[dionaea] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/dionaea/volumes/logs"

# Per-honeypot inbox subdir — server-config created the parent inbox/ with 777.
# Dionaea writes captured binaries here (md5-named); metadata addon canonicalises.
mkdir -p "${DEPLOY_DIR}/inbox/dionaea"
chmod 777 "${DEPLOY_DIR}/inbox/dionaea"

# ── Build image and start stack ───────────────────────────────────────
echo "[dionaea] Building dionaea from source (~15 min on a Nanode)..."
cd "${DEPLOY_DIR}"
docker compose build dionaea

echo "[dionaea] Starting honeypot stack..."
docker compose up -d

echo ""
echo "================================================================"
echo "  Setup complete: ${SERVER_NAME}"
echo ""
echo "  FTP honeypot port  : 21"
echo "  SMB honeypot ports : 139, 445"
echo "  Real SSH port      : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP       : ${TAILSCALE_IP}"
echo ""
echo "  Logs               : ${DEPLOY_DIR}/dionaea/volumes/logs/dionaea.json"
echo "  Sample inbox       : ${DEPLOY_DIR}/inbox/dionaea/"
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo ""
echo "  Useful commands:"
echo "    docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs -f dionaea"
echo "    docker compose -f ${DEPLOY_DIR}/docker-compose.yml ps"
echo "================================================================"
