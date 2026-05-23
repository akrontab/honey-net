#!/usr/bin/env python3
"""Opens an interactive SSH session to the log-stack server."""

import argparse
import os
import subprocess
import sys

from _lib import DEVNULL, load_manifest, load_state, select_backend, ssh_key

def main():
    parser = argparse.ArgumentParser(description="SSH into the log-stack server.")
    parser.add_argument("--port", "-p", type=int, default=65022, metavar="N",
                        help="SSH port (default: 65022)")
    parser.add_argument("--pre-setup", action="store_true",
                        help="Use public IP on port 22 (before setup.sh has run)")
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()
    server  = select_backend(servers, state)

    name  = server["name"]
    key   = ssh_key(server["ssh_key"])
    entry = state.get(name, {})

    if args.pre_setup:
        ip   = entry.get("public_ip")
        port = 22
        if not ip:
            sys.exit(f"No public IP for '{name}' in state.json — run sync_ips.py")
        print(f"Connecting to {name} ({ip}) on port 22 (pre-setup)...")
    else:
        ip   = entry.get("tailscale_ip")
        port = args.port
        if not ip:
            sys.exit(f"No Tailscale IP for '{name}' in state.json — run sync_ips.py")
        print(f"Connecting to {name} ({ip}) on port {port}...")

    cmd = [
        "ssh", "-i", key, "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={DEVNULL}",
        f"root@{ip}",
    ]

    if sys.platform != "win32":
        os.execvp("ssh", cmd)
    else:
        subprocess.run(cmd)

if __name__ == "__main__":
    main()
