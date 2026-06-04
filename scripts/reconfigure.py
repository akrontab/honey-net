#!/usr/bin/env python3
"""Re-apply host hardening config to a live honeypot server without reprovisioning.

Pushes the assembled setup.sh (function library + generated dispatch tail) and the
three conf files over Tailscale :65022, then runs:

    HONEYNET_PHASE=reconfigure bash /root/<name>/setup.sh

The reconfigure phase calls only the idempotent config functions:
    configure_sshd, configure_sysctl, configure_fail2ban,
    configure_ports (open declared ports), reconcile_ports (prune stale ports).

Use this when:
  - A conf file (sshd_hardening.conf, 99-hardening.conf, fail2ban-jail.local) changed
  - A honeypot was added or removed from honey-net.json (port set changes)

Does NOT touch: .env / secrets, compose stack, or docker images (use redeploy for those).
Does NOT re-provision: no apt install, no Docker setup, no Tailscale join.

Usage:
  python reconfigure.py [--server NAME] [--dry-run]
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import load_manifest, load_state
from lib.package import assemble_honeypot_setup, collect_ports, SETUP_CONF_FILES
from lib.server import select_server
from lib.ssh import DEVNULL, ssh_key


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Re-apply host hardening config to a live honeypot server (port 65022). "
            "Reconfigures sshd, sysctl, fail2ban, and UFW port rules without reprovisioning."
        ),
    )
    parser.add_argument("--server", "-s", metavar="NAME", help="Server name from honey-net.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change (validate ports, print conf diffs) without applying")
    args = parser.parse_args()

    servers   = load_manifest()
    state     = load_state()
    server    = select_server(
        servers, state,
        name_arg=args.server,
        filter_fn=lambda s: s["type"] == "honeypot",
        prompt="Select a honeypot server to reconfigure",
    )

    name  = server["name"]
    key   = ssh_key(server["ssh_key"])
    ts_ip = state.get(name, {}).get("tailscale_ip")

    if not ts_ip:
        sys.exit(f"No Tailscale IP for '{name}' in state.json — run sync_ips.py first")

    # Validate ports and show what will happen.
    print(f"\nValidating port declarations for {name}...")
    port_map = collect_ports(server)
    if port_map:
        print("  Ports declared in package.toml (will be ensured open in UFW):")
        for port in sorted(port_map):
            print(f"    {port}/tcp  ({port_map[port]})")
    else:
        print("  No honeypot ports declared.")
    print("  UFW rules for any other ports will be pruned.")

    if args.dry_run:
        print("\n[dry-run] No changes applied.")
        return

    ssh_opts = ["-i", key, "-p", "65022",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"UserKnownHostsFile={DEVNULL}"]
    remote = f"root@{ts_ip}"

    with tempfile.TemporaryDirectory() as tmp:
        cfg_dir = Path(tmp) / name
        cfg_dir.mkdir()

        print(f"\nAssembling config package for {name}...")
        assemble_honeypot_setup(server, cfg_dir)

        print(f"Copying config to {remote} (port 65022)...")
        r = subprocess.run([
            "scp", "-r", "-P", "65022", "-i", key,
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={DEVNULL}",
            str(cfg_dir), f"{remote}:/root/",
        ])
        if r.returncode != 0:
            sys.exit(f"Transfer failed (scp exit {r.returncode})")

    print(f"Running reconfigure on {name}...")
    r = subprocess.run([
        "ssh", *ssh_opts, remote,
        f"HONEYNET_PHASE=reconfigure bash /root/{name}/setup.sh",
    ])
    if r.returncode != 0:
        sys.exit(f"Reconfigure failed (ssh exit {r.returncode})")

    # Show resulting UFW state as confirmation.
    print(f"\nUFW status on {name}:")
    subprocess.run(["ssh", *ssh_opts, remote, "ufw status"])

    print(f"\n{name} reconfigured successfully.")


if __name__ == "__main__":
    main()
