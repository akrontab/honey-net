# Metadata extractor fragment — appended to setup.sh by deploy.py.
# The shared inbox at ${DEPLOY_DIR}/inbox is created by server-config; per-honeypot
# subdirs (e.g. inbox/cowrie/, inbox/dionaea/) are created by each honeypot's fragment.

# ── Build image ───────────────────────────────────────────────────────
echo "[metadata] Building metadata image..."
cd "${DEPLOY_DIR}"
docker compose build metadata

echo "[metadata] Metadata extractor configured."
