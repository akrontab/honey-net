#!/usr/bin/env python3
"""Copies the deploy/ folder to the log-stack server."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _lib import DEVNULL, LOGSTACK_ROOT, load_manifest, load_state, select_backend, ssh_key

def main():
    parser = argparse.ArgumentParser(
        description="Deploy log-stack files to the server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Default: port 22 (use before setup.sh has run).\n"
            "--post-setup: port 65022 via Tailscale (use after setup.sh)."
        ),
    )
    parser.add_argument("--port", "-p", type=int, default=22, metavar="N",
                        help="SSH/SCP port (default: 22)")
    parser.add_argument("--post-setup", action="store_true",
                        help="Shorthand for --port 65022 (after setup.sh has run)")
    parser.add_argument("--user", "-u", default="root", metavar="USER")
    args = parser.parse_args()

    port = 65022 if args.post_setup else args.port

    servers = load_manifest()
    state   = load_state()
    server  = select_backend(servers, state)

    name  = server["name"]
    key   = ssh_key(server["ssh_key"])
    entry = state.get(name, {})

    if port == 22:
        ip = entry.get("public_ip")
        if not ip:
            sys.exit(f"No public IP for '{name}' in state.json — run sync_ips.py after terraform apply")
    else:
        ip = entry.get("tailscale_ip")
        if not ip:
            sys.exit(f"No Tailscale IP for '{name}' in state.json — run sync_ips.py")

    user    = args.user
    src     = LOGSTACK_ROOT / "deploy"
    project = LOGSTACK_ROOT.name   # "log-stack"

    ssh_opts = ["-i", key, "-p", str(port),
                "-o", "StrictHostKeyChecking=no",
                "-o", f"UserKnownHostsFile={DEVNULL}"]

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / project
        print("Staging deploy/ files...")
        shutil.copytree(src, pkg, ignore=shutil.ignore_patterns(".env"))

        print(f"Copying to {user}@{ip}:/root/ on port {port}...")
        r = subprocess.run(["scp", "-r"] + ssh_opts + [str(pkg), f"{user}@{ip}:/root/"])
        if r.returncode != 0:
            sys.exit(f"Transfer failed (scp exit {r.returncode})")

    remote_dir = f"/root/{project}"
    print("Fixing permissions on server...")
    r = subprocess.run(
        ["ssh"] + ssh_opts + [f"{user}@{ip}",
         f"find {remote_dir} -type d -exec chmod 755 {{}} \\; "
         f"&& find {remote_dir} -type f -exec chmod 644 {{}} \\; "
         f"&& chmod +x {remote_dir}/setup/setup.sh"],
    )
    if r.returncode != 0:
        print("Warning: permission fix failed — you may need to run chmod manually", file=sys.stderr)

    print(f"""
Done. Next steps:
  1. SSH into the server:
       ssh -i {key} -p {port} {user}@{ip}
  2. Verify your SSH key is in ~/.ssh/authorized_keys
  3. Run the setup script:
       sudo bash {remote_dir}/setup/setup.sh
  4. Reconnect on port 65022 when setup completes:
       ssh -i {key} -p 65022 {user}@{ip}

Re-deploying after setup? Use: python deploy.py --post-setup
""")

if __name__ == "__main__":
    main()
