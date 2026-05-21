import json
from datetime import datetime, timezone

from config import HONEYPOT_HOSTNAME, LOG_FILE


def log_event(event_type, peer, **kwargs):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event":     event_type,
        "src_ip":    peer[0],
        "src_port":  peer[1],
        "server":    HONEYPOT_HOSTNAME,
        **kwargs,
    }
    line = json.dumps(entry)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)
