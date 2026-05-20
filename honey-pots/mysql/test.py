#!/usr/bin/env python3
"""Connects to port 3306 and reads the MySQL server greeting to verify the honeypot is up."""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from _lib import load_manifest, load_state, select_server, ssh_key

def main():
    servers = load_manifest()
    state   = load_state()
    server  = select_server(
        servers, state,
        filter_fn=lambda s: "mysql" in s.get("honeypots", []),
        prompt="Select a server to test",
    )

    name  = server["name"]
    entry = state.get(name, {})
    ip    = entry.get("public_ip")

    if not ip:
        sys.exit(f"No public IP for '{name}' in state.json — run sync_ips.py after terraform apply")

    print(f"Connecting to {ip}:3306 ({name})...")
    try:
        with socket.create_connection((ip, 3306), timeout=5) as s:
            s.settimeout(3)
            data = s.recv(512)
        if len(data) > 5:
            # Skip 4-byte packet header; version string starts at byte 5
            version = data[5:36].split(b"\x00")[0].decode("ascii", errors="replace")
            print(f"OK — server greeted with MySQL {version}")
        else:
            print(f"Connected but received unexpected response ({len(data)} bytes).")
    except Exception as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
