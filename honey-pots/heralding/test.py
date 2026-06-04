#!/usr/bin/env python3
"""Smoke-tests a running heralding deployment."""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from _lib import load_manifest, load_state, select_server


def check_port(ip: str, port: int, expect_prefix: bytes | None = None,
               send: bytes | None = None, label: str = "") -> bool:
    tag = label or f"port {port}"
    try:
        with socket.create_connection((ip, port), timeout=5) as s:
            s.settimeout(3)
            if send:
                s.sendall(send)
            data = s.recv(512)
        if expect_prefix and not data.startswith(expect_prefix):
            print(f"  {tag}: unexpected banner: {data[:48]!r}", file=sys.stderr)
            return False
        print(f"  {tag}: OK ({len(data)} bytes, {data[:32]!r})")
        return True
    except Exception as e:
        print(f"  {tag}: FAILED — {e}", file=sys.stderr)
        return False


def main():
    servers = load_manifest()
    state   = load_state()
    server  = select_server(
        servers, state,
        filter_fn=lambda s: "heralding" in s.get("honeypots", []),
        prompt="Select a server to test",
    )

    name = server["name"]
    ip   = state.get(name, {}).get("public_ip")
    if not ip:
        sys.exit(f"No public IP for '{name}' — run sync_ips.py")

    print(f"Testing heralding on {ip} ({name})...\n")
    results = [
        check_port(ip, 21,   expect_prefix=b"220", label="FTP      :21"),
        check_port(ip, 22,   expect_prefix=b"SSH-", label="SSH      :22"),
        check_port(ip, 25,   expect_prefix=b"220", label="SMTP     :25"),
        check_port(ip, 80,   send=b"GET / HTTP/1.0\r\n\r\n", label="HTTP     :80"),
        check_port(ip, 110,  expect_prefix=b"+OK",  label="POP3     :110"),
        check_port(ip, 3306, label="MySQL    :3306"),
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
