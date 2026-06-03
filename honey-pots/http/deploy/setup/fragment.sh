# HTTP honeypot fragment — appended to server-config/setup.sh by provision.py.
# Runs after base hardening and Tailscale are in place.
# Build-only: a later component's fragment runs `docker compose up -d`
# (on mysql-ssh the terminal addon is malware-sender). Keep `http` ahead of a
# component that starts the stack, or this pot is built but never started.

# ── Open honeypot ports ───────────────────────────────────────────────
echo "[http] Opening HTTP honeypot ports 80 and 443..."
ufw allow "80/tcp" comment 'http honeypot'
ufw allow "443/tcp" comment 'http honeypot TLS'

# ── Create volume directories ─────────────────────────────────────────
echo "[http] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/http/volumes/logs"
chown honey:honey "${DEPLOY_DIR}/http/volumes/logs"

# ── Generate self-signed TLS certificate ─────────────────────────────
echo "[http] Generating self-signed TLS certificate..."
mkdir -p "${DEPLOY_DIR}/http/tls"
openssl req -x509 -newkey rsa:2048 \
    -keyout "${DEPLOY_DIR}/http/tls/key.pem" \
    -out    "${DEPLOY_DIR}/http/tls/cert.pem" \
    -days 3650 -nodes \
    -subj "/CN=localhost/O=Acme Corp/C=US" \
    2>/dev/null
chmod 600 "${DEPLOY_DIR}/http/tls/key.pem"
chown honey:honey "${DEPLOY_DIR}/http/tls/key.pem" "${DEPLOY_DIR}/http/tls/cert.pem"

# Per-honeypot inbox subdir — server-config created the parent inbox/ with 777.
mkdir -p "${DEPLOY_DIR}/inbox/http"
chmod 777 "${DEPLOY_DIR}/inbox/http"

# ── Build image (a later fragment starts the stack) ───────────────────
echo "[http] Building http honeypot image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build http"

echo "[http] HTTP configured — stack will start after all addons are set up."
