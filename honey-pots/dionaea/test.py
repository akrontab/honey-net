#!/usr/bin/env python3
"""Smoke-tests a running dionaea deployment (FTP on 21, SMB on 445)."""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from _lib import load_manifest, load_state, select_server


def check_port(ip: str, port: int, expect_prefix: bytes | None = None, label: str = "") -> bool:
    tag = label or f"port {port}"
    try:
        with socket.create_connection((ip, port), timeout=5) as s:
            s.settimeout(3)
            data = s.recv(512)
        if expect_prefix and not data.startswith(expect_prefix):
            print(f"  {tag}: unexpected banner: {data[:32]!r}", file=sys.stderr)
            return False
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
        filter_fn=lambda s: "dionaea" in s.get("honeypots", []),
        prompt="Select a server to test",
    )

    name = server["name"]
    ip   = state.get(name, {}).get("public_ip")
    if not ip:
        sys.exit(f"No public IP for '{name}' — run sync_ips.py")

    print(f"Testing dionaea on {ip} ({name})...\n")
    results = [
        check_port(ip, 21,  expect_prefix=b"220", label="FTP  :21 "),
        check_port(ip, 445, label="SMB  :445"),
        check_port(ip, 139, label="SMB  :139"),
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
