import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def load_manifest():
    path = REPO_ROOT / "honey-net.json"
    if not path.exists():
        sys.exit("honey-net.json not found")
    return json.loads(path.read_text(encoding="utf-8"))


def load_state():
    path = REPO_ROOT / "state.json"
    if not path.exists():
        sys.exit("state.json not found — run sync_ips.py after terraform apply")
    return json.loads(path.read_text(encoding="utf-8"))
