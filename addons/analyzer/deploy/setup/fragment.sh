# Analyzer fragment — appended to setup.sh by deploy.py.
# This is the last fragment — it builds the analyzer image and starts the stack.

# ── Build image ───────────────────────────────────────────────────────
echo "[analyzer] Building analyzer image..."
cd "${DEPLOY_DIR}"
docker compose build analyzer

# ── Start full stack ──────────────────────────────────────────────────
echo "[analyzer] Starting stack..."
docker compose up -d

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  Stack started. Useful commands:                        │"
echo "│                                                         │"
echo "│  docker compose -f /opt/${SERVER_NAME}/docker-compose.yml logs -f metadata  │"
echo "│  docker compose -f /opt/${SERVER_NAME}/docker-compose.yml logs -f analyzer  │"
echo "└─────────────────────────────────────────────────────────┘"
