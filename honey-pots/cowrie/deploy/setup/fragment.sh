# Cowrie honeypot fragment — appended to server-config/setup.sh by deploy.ps1.
# Runs after base hardening and Tailscale are in place.
# Adds cowrie-specific UFW ports, creates volume directories, and starts the stack.

# ── Create volume directories ─────────────────────────────────────────
echo "[cowrie] Creating volume directories..."
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/var/log/cowrie"
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/var/lib/cowrie"
mkdir -p "${DEPLOY_DIR}/cowrie/volumes/logs"

# Per-honeypot inbox subdir — server-config created the parent inbox/ with 777.
mkdir -p "${DEPLOY_DIR}/inbox/cowrie"
chmod 777 "${DEPLOY_DIR}/inbox/cowrie"

# Cowrie runs as UID 999 inside the container. In rootless Docker, container UIDs >= 1
# map to host subUIDs: container UID N → HONEY_SUBUID_START + N - 1.
# So UID 999 inside → (HONEY_SUBUID_START + 998) on the host.
find "${DEPLOY_DIR}/cowrie/cowrie" -type d -exec chmod 755 {} \;
find "${DEPLOY_DIR}/cowrie/cowrie" -type f -exec chmod 644 {} \;
COWRIE_HOST_UID=$(( HONEY_SUBUID_START + 999 - 1 ))
chown -R "${COWRIE_HOST_UID}:${COWRIE_HOST_UID}" "${DEPLOY_DIR}/cowrie/volumes"

# ── Build images (sequence matters — concurrent BuildKit crashes dockerd) ─────
echo "[cowrie] Building cowrie image (with key-harvester extension)..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build cowrie"

echo "[cowrie] Building capture-writer image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build capture-writer"

echo "[cowrie] Cowrie configured — stack will start after all addons are set up."
