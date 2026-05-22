#!/usr/bin/env python3
"""Opens an interactive SSH session to a server."""

import argparse
import os
import subprocess
import sys

from lib.config import load_manifest, load_state
from lib.server import select_server
from lib.ssh import DEVNULL, ssh_key

def main():
    parser = argparse.ArgumentParser(
        description="Open an SSH session to a honey-net server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Default:    Port 65022 via Tailscale IP (after setup.sh has run).\n"
            "--pre-setup Port 22 via public IP (before setup.sh runs)."
        ),
    )
    parser.add_argument("--server", "-s", metavar="NAME", help="Server name from honey-net.json")
    parser.add_argument("--pre-setup", action="store_true",
                        help="Connect via public IP on port 22 (pre-provisioning)")
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()
    server  = select_server(servers, state, name_arg=args.server, prompt="Select a server to connect to")

    name    = server["name"]
    key     = ssh_key(server["ssh_key"])
    entry   = state.get(name, {})

    if args.pre_setup:
        ip = entry.get("public_ip")
        if not ip:
            sys.exit(f"No public IP for '{name}' in state.json — run sync_ips.py after terraform apply")
        port = 22
        print(f"Connecting to {name} ({ip}) on port 22 (pre-setup)...")
    else:
        ip = entry.get("tailscale_ip")
        if not ip:
            print(f"Error: no Tailscale IP for '{name}' in state.json.", file=sys.stderr)
            print(f"  Run sync_ips.py, or if this is a fresh server: python connect.py -s {name} --pre-setup",
                  file=sys.stderr)
            sys.exit(1)
        port = 65022
        print(f"Connecting to {name} ({ip}) on port 65022...")

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
