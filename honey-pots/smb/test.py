#!/usr/bin/env python3
"""Smoke-tests a running smb honeypot deployment (ports 139 and 445)."""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from _lib import load_manifest, load_state, select_server


def check_port(ip: str, port: int, label: str = "") -> bool:
    tag = label or f"port {port}"
    try:
        with socket.create_connection((ip, port), timeout=5) as s:
            s.settimeout(3)
            data = s.recv(512)
        print(f"  {tag}: OK ({len(data)} bytes)")
        return True
    except Exception as e:
        print(f"  {tag}: FAILED — {e}", file=sys.stderr)
        return False


def main():
    servers = load_manifest()
    state   = load_state()
    server  = select_server(
        servers, state,
        filter_fn=lambda s: "smb" in s.get("honeypots", []),
        prompt="Select a server to test",
    )

    name = server["name"]
    ip   = state.get(name, {}).get("public_ip")
    if not ip:
        sys.exit(f"No public IP for '{name}' — run sync_ips.py")

    print(f"Testing smb on {ip} ({name})...\n")
    results = [
        check_port(ip, 445, "SMB  :445"),
        check_port(ip, 139, "SMB  :139"),
    ]

    print()
    if all(results):
        print("All checks passed.")
    else:
        failed = results.count(False)
        print(f"{failed} check(s) failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
