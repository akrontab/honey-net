#!/usr/bin/env python3
"""Updates a live server over Tailscale (port 65022). Does not touch system configuration."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from _lib import DEVNULL, REPO_ROOT, assemble_honeypot_package, copy_tree, load_manifest, load_state, select_server, ssh_key

# Map honeypot type → Docker service name that has a build: context.
# Build images sequentially to avoid concurrent BuildKit builds crashing dockerd.
BUILD_MAP = {
    "cowrie": "analyzer",
    "mysql":  "mysql-honeypot",
}

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Update a live server via Tailscale (port 65022). "
            "Does not touch system configuration — only updates service files and restarts the stack."
        ),
    )
    parser.add_argument("--server", "-s", metavar="NAME", help="Server name from honey-net.json")
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()
    server  = select_server(servers, state, name_arg=args.server, prompt="Select a server to redeploy")

    name   = server["name"]
    key    = ssh_key(server["ssh_key"])
    entry  = state.get(name, {})
    ts_ip  = entry.get("tailscale_ip")

    if not ts_ip:
        sys.exit(f"No Tailscale IP for '{name}' in state.json — run sync_ips.py (Tailscale must be active)")

    ssh_opts = ["-i", key, "-p", "65022",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"UserKnownHostsFile={DEVNULL}"]
    remote = f"root@{ts_ip}"

    with tempfile.TemporaryDirectory() as tmp:
        pkg_dir = Path(tmp) / name

        if server["type"] == "backend":
            src = REPO_ROOT / name / "deploy"
            if not src.exists():
                sys.exit(f"Backend deploy folder not found: {src}")
            print(f"Staging {name} (backend)...")
            copy_tree(src, pkg_dir, exclude_names={".env"})

        elif server["type"] == "honeypot":
            print(f"Assembling updated package for {name}...")
            pkg_dir.mkdir()
            assemble_honeypot_package(server, pkg_dir)

        else:
            sys.exit(f"Unknown server type '{server['type']}' for '{name}'")

        print(f"Copying to {remote} (port 65022)...")
        r = subprocess.run([
            "scp", "-r", "-P", "65022", "-i", key,
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={DEVNULL}",
            str(pkg_dir), f"{remote}:/root/",
        ])
        if r.returncode != 0:
            sys.exit(f"Transfer failed (scp exit {r.returncode})")

    # Build remote restart command
    compose_cmd = f"docker compose -f /opt/{name}/docker-compose.yml"
    rsync_cmd   = (
        f"rsync -a --delete --exclude='.env' --filter='protect */volumes/' "
        f"/root/{name}/ /opt/{name}/ "
        f"&& chmod -R a+rX /opt/{name}/"
    )

    if server["type"] == "honeypot":
        build_cmds = " && ".join(
            f"{compose_cmd} build {BUILD_MAP[hp]}"
            for hp in server["honeypots"]
            if hp in BUILD_MAP
        )
        if build_cmds:
            restart_cmd = f"{rsync_cmd} && {build_cmds} && {compose_cmd} up -d"
        else:
            restart_cmd = f"{rsync_cmd} && {compose_cmd} up -d"
    else:
        restart_cmd = f"{rsync_cmd} && {compose_cmd} up -d"

    print(f"Restarting stack on {name}...")
    r = subprocess.run(["ssh"] + ssh_opts + [remote, restart_cmd])
    if r.returncode != 0:
        sys.exit(f"Stack restart failed (ssh exit {r.returncode})")

    print(f"\n{name} redeployed successfully.")

if __name__ == "__main__":
    main()
