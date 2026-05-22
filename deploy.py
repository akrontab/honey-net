#!/usr/bin/env python3
"""First deploy to a fresh server (port 22, before setup.sh hardens the host)."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from lib.config import REPO_ROOT, load_manifest, load_state
from lib.files import copy_tree
from lib.package import assemble_honeypot_package
from lib.server import select_server
from lib.ssh import DEVNULL, ssh_key

CONF_FILES = ["sshd_hardening.conf", "99-hardening.conf", "fail2ban-jail.local"]

def stage_backend(server, pkg_dir):
    src = REPO_ROOT / server["name"] / "deploy"
    if not src.exists():
        sys.exit(f"Backend deploy folder not found: {src}")
    print(f"Staging {server['name']} (backend)...")
    copy_tree(src, pkg_dir, exclude_names={".env"})

def stage_honeypot(server, pkg_dir):
    name = server["name"]
    print(f"Assembling deploy package for {name}...")
    pkg_dir.mkdir()

    assemble_honeypot_package(server, pkg_dir)

    # Copy server-config conf files so setup.sh can reference them via $SCRIPT_DIR
    for cf in CONF_FILES:
        src = REPO_ROOT / "server-config" / cf
        if not src.exists():
            sys.exit(f"server-config/{cf} not found")
        (pkg_dir / cf).write_bytes(src.read_bytes())

    # Concatenate server-config/setup.sh + each honeypot's fragment.sh
    base_sh = REPO_ROOT / "server-config" / "setup.sh"
    if not base_sh.exists():
        sys.exit("server-config/setup.sh not found")
    setup = base_sh.read_text(encoding="utf-8")
    for hp in server.get("honeypots", []):
        fragment = REPO_ROOT / "honey-pots" / hp / "deploy" / "setup" / "fragment.sh"
        if fragment.exists():
            setup += f"\n\n# --- {hp} ---\n"
            setup += fragment.read_text(encoding="utf-8")
        else:
            print(f"  Warning: no fragment.sh for '{hp}' — skipping", file=sys.stderr)
    for addon in server.get("addons", []):
        fragment = REPO_ROOT / "addons" / addon / "deploy" / "setup" / "fragment.sh"
        if fragment.exists():
            setup += f"\n\n# --- {addon} ---\n"
            setup += fragment.read_text(encoding="utf-8")
        else:
            print(f"  Warning: no fragment.sh for addon '{addon}' — skipping", file=sys.stderr)
    (pkg_dir / "setup.sh").write_text(setup, encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(
        description="First deploy to a fresh server. Use redeploy.py for subsequent updates.",
    )
    parser.add_argument("--server", "-s", metavar="NAME", help="Server name from honey-net.json")
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()
    server  = select_server(servers, state, name_arg=args.server, prompt="Select a server to deploy")

    name   = server["name"]
    key    = ssh_key(server["ssh_key"])
    entry  = state.get(name, {})
    pub_ip = entry.get("public_ip")

    if not pub_ip:
        sys.exit(f"No public IP for '{name}' in state.json — run sync_ips.py after terraform apply")

    with tempfile.TemporaryDirectory() as tmp:
        pkg_dir = Path(tmp) / name

        if server["type"] == "backend":
            stage_backend(server, pkg_dir)
        elif server["type"] == "honeypot":
            stage_honeypot(server, pkg_dir)
        else:
            sys.exit(f"Unknown server type '{server['type']}' for '{name}'")

        print(f"Copying to root@{pub_ip} (port 22)...")
        r = subprocess.run([
            "scp", "-r", "-P", "22", "-i", key,
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={DEVNULL}",
            str(pkg_dir), f"root@{pub_ip}:/root/",
        ])
        if r.returncode != 0:
            sys.exit(f"Transfer failed (scp exit {r.returncode})")

    print(f"""
Deployed to /root/{name} on {pub_ip}

Next steps:
  1. Verify your SSH key is in ~/.ssh/authorized_keys on the server
     (setup.sh disables password auth — if your key is missing you will be locked out)

  2. SSH in:
       ssh -i {key} -p 22 root@{pub_ip}

  3. Run setup:
       sudo bash /root/{name}/setup.sh

  After setup completes, port 22 is closed. SSH moves to port 65022 (Tailscale only).
  Run sync_ips.py to capture the Tailscale IP, then use redeploy.py for future updates.
""")

if __name__ == "__main__":
    main()
