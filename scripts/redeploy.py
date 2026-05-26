#!/usr/bin/env python3
"""Updates a live server over Tailscale (port 65022). Does not touch system configuration."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import REPO_ROOT, load_manifest, load_state
from lib.files import copy_tree
from lib.package import assemble_honeypot_package, backend_build_services, component_build_services
from lib.server import select_server
from lib.ssh import DEVNULL, ssh_key

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
        f"&& find /opt/{name}/ -not -path '*/volumes/*' -exec chmod a+rX {{}} +"
    )

    if server["type"] == "honeypot":
        components = (
            [(hp, "honey-pots") for hp in server.get("honeypots", [])] +
            [(a,  "addons")     for a  in server.get("addons",    [])]
        )
        build_svcs = [
            svc
            for name, base in components
            for svc in component_build_services(name, base)
        ]
        build_cmds = " && ".join(f"{compose_cmd} build {svc}" for svc in build_svcs)
        if build_cmds:
            restart_cmd = f"{rsync_cmd} && {build_cmds} && {compose_cmd} up -d"
        else:
            restart_cmd = f"{rsync_cmd} && {compose_cmd} up -d"
    else:
        build_svcs = backend_build_services(name)
        build_cmds = " && ".join(f"{compose_cmd} build {svc}" for svc in build_svcs)
        if build_cmds:
            restart_cmd = f"{rsync_cmd} && {build_cmds} && {compose_cmd} up -d"
        else:
            restart_cmd = f"{rsync_cmd} && {compose_cmd} up -d"

    print(f"Restarting stack on {name}...")
    r = subprocess.run(["ssh"] + ssh_opts + [remote, restart_cmd])
    if r.returncode != 0:
        sys.exit(f"Stack restart failed (ssh exit {r.returncode})")

    print(f"\n{name} redeployed successfully.")

if __name__ == "__main__":
    main()
