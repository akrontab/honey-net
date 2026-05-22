# Metadata extractor fragment — appended to setup.sh by deploy.py.

# ── Create shared inbox directory ─────────────────────────────────────
# Shared with cowrie (writes binaries) and analyzer (reads + submits).
# 777 so both Cowrie (UID 999) and root containers can write.
echo "[metadata] Creating shared inbox..."
mkdir -p "${DEPLOY_DIR}/inbox"
chmod 777 "${DEPLOY_DIR}/inbox"

# ── Create state directory for offset tracking ────────────────────────
mkdir -p "${DEPLOY_DIR}/metadata/volumes/state"

# ── Build image ───────────────────────────────────────────────────────
echo "[metadata] Building metadata image..."
cd "${DEPLOY_DIR}"
docker compose build metadata

echo "[metadata] Metadata extractor configured."
