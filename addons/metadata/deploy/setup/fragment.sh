# Metadata extractor fragment — appended to setup.sh by deploy.py.
# The shared inbox at ${DEPLOY_DIR}/inbox is created by server-config; per-honeypot
# subdirs (e.g. inbox/cowrie/) are created by each honeypot's fragment.

# ── Build image ───────────────────────────────────────────────────────
echo "[metadata] Building metadata image..."
su -s /bin/bash honey -c "cd ${DEPLOY_DIR} && ${HONEY_DC} build metadata"

echo "[metadata] Metadata extractor configured."
