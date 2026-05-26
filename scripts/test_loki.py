#!/usr/bin/env python3
"""Pushes a test log line to Loki over Tailscale to verify the full stack is working."""

import argparse
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from lib.color import green, red
from lib.config import load_manifest, load_state
from lib.server import select_server


def _no_response(loki_host):
    print(f"\n{red('No response')} from http://{loki_host}:3100 — cannot reach Loki.\n")
    print("Checklist:")
    print(f"  1. Tailscale is connected on this machine:   tailscale status")
    print(f"  2. log-stack host is reachable:              tailscale ping {loki_host}")
    print(f"  3. Loki container is running (on server):    docker compose -f /opt/log-stack/docker-compose.yml ps")
    print(f"  4. Loki is bound to the right IP (on server): ss -tlnp | grep 3100")


def main():
    parser = argparse.ArgumentParser(
        description="Push a test log line to Loki and verify the stack is working.",
    )
    parser.add_argument("--loki-host", metavar="IP",
                        help="Tailscale IP of the log-stack server (skips auto-detect from state.json)")
    args = parser.parse_args()

    r = subprocess.run(["tailscale", "status"], capture_output=True)
    if r.returncode != 0:
        sys.exit("Tailscale is not running. Start it and try again.")

    if args.loki_host:
        loki_host = args.loki_host
    else:
        servers = load_manifest()
        state   = load_state()
        server  = select_server(
            servers, state,
            filter_fn=lambda s: s["type"] == "backend",
            prompt="Select a log-stack server",
        )
        name      = server["name"]
        loki_host = state.get(name, {}).get("tailscale_ip")
        if not loki_host:
            sys.exit(f"No Tailscale IP for '{name}' in state.json — run sync_ips.py")
        print(f"Using {name} Tailscale IP: {loki_host}")

    ts_ns   = str(time.time_ns())
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    host    = socket.gethostname().lower()
    message = f"honey-net connectivity test from {host} at {now_utc} UTC"

    url  = f"http://{loki_host}:3100/loki/api/v1/push"
    body = {
        "streams": [
            {
                "stream": {"job": "test", "host": host},
                "values": [[ts_ns, message]],
            }
        ]
    }

    print(f"Pushing test log to {url} ...")
    try:
        resp = requests.post(url, json=body, timeout=10)
    except requests.exceptions.ConnectionError:
        _no_response(loki_host)
        sys.exit(1)

    if resp.status_code == 204:
        print(f"\n{green('Success (HTTP 204)')} — log line accepted by Loki.")
        print(f"\nVerify in Grafana (http://{loki_host}:3000):")
        print('  Explore → Loki → query: {job="test"}')
        print(f"\nExpected log line:\n  {message}")
    else:
        print(f"\n{red(f'Loki returned HTTP {resp.status_code}')}")
        print(f"Body: {resp.text[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
