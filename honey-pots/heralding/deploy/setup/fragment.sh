# Heralding honeypot fragment — appended to server-config/setup.sh by provision.py.
# Runs after base hardening and Tailscale are in place.
# Heralding is a multi-protocol credential honeypot (Mode B wrap: thin Dockerfile
# pinning heralding==1.0.7 from PyPI). Uses network_mode: host + pasta for real
# attacker src_ip preservation — same pattern as Cowrie.

# ── Open honeypot ports ───────────────────────────────────────────────
echo "[heralding] Opening honeypot ports..."
ufw allow "21/tcp"   comment 'heralding ftp'
ufw allow "22/tcp"   comment 'heralding ssh'
ufw allow "23/tcp"   comment 'heralding telnet'
ufw allow "25/tcp"   comment 'heralding smtp'
ufw allow "80/tcp"   comment 'heralding http'
ufw allow "110/tcp"  comment 'heralding pop3'
ufw allow "143/tcp"  comment 'heralding imap'
ufw allow "443/tcp"  comment 'heralding https'
ufw allow "1080/tcp" comment 'heralding socks5'
ufw allow "3306/tcp" comment 'heralding mysql'
ufw allow "5432/tcp" comment 'heralding postgresql'
ufw allow "5900/tcp" comment 'heralding vnc'

# ── Create volume directories ─────────────────────────────────────────
echo "[heralding] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/heralding/volumes/logs"
chown honey:honey "${DEPLOY_DIR}/heralding/volumes/logs"

# ── Build image and start stack ───────────────────────────────────────
echo "[heralding] Building heralding image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build heralding"

echo "[heralding] Starting stack..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} up -d"

echo ""
echo "================================================================"
echo "  Setup complete: ${SERVER_NAME} (heralding component)"
echo ""
echo "  Heralding ports (enabled in heralding.yml):"
echo "    FTP :21  Telnet :23  SSH :22  SMTP :25"
echo "    HTTP :80  HTTPS :443  POP3 :110  IMAP :143"
echo "    MySQL :3306  PostgreSQL :5432  VNC :5900  SOCKS5 :1080"
echo "  Real SSH port      : ${REAL_SSH_PORT} (Tailscale only)"
echo "  Tailscale IP       : ${TAILSCALE_IP}"
echo ""
echo "  Auth log           : ${DEPLOY_DIR}/heralding/volumes/logs/log_auth.csv"
echo "  Session log        : ${DEPLOY_DIR}/heralding/volumes/logs/log_session.json"
echo ""
if [[ -n "${LOKI_HOST}" ]]; then
  echo "  Shipping logs to Loki at: http://${LOKI_HOST}:3100"
else
  echo "  LOKI_HOST not set — edit ${DEPLOY_DIR}/.env and restart the stack"
fi
echo "================================================================"
