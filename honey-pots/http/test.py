#!/usr/bin/env python3
"""Smoke-tests a running http honeypot deployment (port 80)."""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from _lib import load_manifest, load_state, select_server


def check_http(ip: str, port: int = 80, label: str = "HTTP :80") -> bool:
    try:
        with socket.create_connection((ip, port), timeout=5) as s:
            s.settimeout(3)
            s.sendall(b"GET / HTTP/1.0\r\nHost: test\r\n\r\n")
            data = s.recv(512)
        if not data.startswith(b"HTTP/"):
            print(f"  {label}: unexpected response: {data[:32]!r}", file=sys.stderr)
            return False
        print(f"  {label}: OK ({data.split(chr(13).encode())[0].decode(errors='replace')})")
        return True
    except Exception as e:
        print(f"  {label}: FAILED — {e}", file=sys.stderr)
        return False


def main():
    servers = load_manifest()
    state   = load_state()
    server  = select_server(
        servers, state,
        filter_fn=lambda s: "http" in s.get("honeypots", []),
        prompt="Select a server to test",
    )

    name = server["name"]
    ip   = state.get(name, {}).get("public_ip")
    if not ip:
        sys.exit(f"No public IP for '{name}' — run sync_ips.py")

    print(f"Testing http on {ip} ({name})...\n")
    results = [check_http(ip, 80)]

    print()
    if all(results):
        print("All checks passed.")
    else:
        failed = results.count(False)
        print(f"{failed} check(s) failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
