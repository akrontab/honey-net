#!/usr/bin/env python3
"""Deploy the alerting detector to the log-stack host."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import REPO_ROOT, load_manifest, load_state
from lib.files import copy_tree
from lib.ssh import DEVNULL, scp_args, ssh_base_args, ssh_key


def main():
    servers = load_manifest()
    state   = load_state()

    log_stack = next((s for s in servers if s["name"] == "log-stack"), None)
    if not log_stack:
        sys.exit("No 'log-stack' entry in honey-net.json")

    name   = log_stack["name"]
    key    = ssh_key(log_stack["ssh_key"])
    ts_ip  = state.get(name, {}).get("tailscale_ip")
    if not ts_ip:
        sys.exit("No Tailscale IP for log-stack in state.json — run sync_ips.py")

    catalog_entry = next((s for s in servers if s["name"] == "malware-catalog"), None)
    catalog_ip    = state.get("malware-catalog", {}).get("tailscale_ip", "") if catalog_entry else ""
    catalog_url   = f"http://{catalog_ip}:8000" if catalog_ip else ""

    remote_dir = "/opt/log-stack/alerting"
    remote     = f"root@{ts_ip}"

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "alerting"
        print("Staging alerting deploy files...")
        copy_tree(REPO_ROOT / "alerting" / "deploy", staging, exclude_names={".env"})

        # Write .env from state.json values — not committed to the repo
        (staging / ".env").write_text(
            f"LOKI_HOST={ts_ip}\nCATALOG_URL={catalog_url}\n",
            encoding="utf-8",
            newline="\n",
        )

        # Deploy config files the detector reads at runtime
        operators_src = REPO_ROOT / "operators.json"
        if operators_src.exists():
            shutil.copy2(operators_src, staging / "operators.json")
        else:
            (staging / "operators.json").write_text(
                '{"operator_ips": []}\n', encoding="utf-8", newline="\n"
            )

        shutil.copy2(REPO_ROOT / "honey-net.json", staging / "honey-net.json")

        print(f"Copying to {remote}...")
        r = subprocess.run(scp_args(key, 65022) + [str(staging), f"{remote}:/root/"])
        if r.returncode != 0:
            sys.exit(f"Transfer failed (scp exit {r.returncode})")

    honey_uid = "$(id -u honey)"
    honey_sock = f"unix:///run/user/{honey_uid}/docker.sock"

    rsync_cmd = (
        f"mkdir -p {remote_dir}/volumes/detector && "
        f"rsync -a --delete --exclude='.env' --filter='protect */volumes/' "
        f"/root/alerting/ {remote_dir}/ "
        f"&& find {remote_dir}/ -not -path '*/volumes/*' -exec chown honey:honey {{}} + "
        f"&& find {remote_dir}/ -not -path '*/volumes/*' -exec chmod a+rX {{}} +"
    )

    def honey(cmd: str) -> str:
        uid = "$HONEY_UID"
        return (
            f'su -s /bin/bash honey -c "'
            f"export XDG_RUNTIME_DIR=/run/user/{uid} "
            f"DOCKER_HOST=unix:///run/user/{uid}/docker.sock && "
            f'cd {remote_dir} && {cmd}"'
        )

    restart_cmd = (
        f"HONEY_UID={honey_uid} && "
        f"{rsync_cmd} && "
        f"{honey('docker compose build detector && docker compose up -d')}"
    )

    print(f"Deploying alerting detector on log-stack...")
    r = subprocess.run(ssh_base_args(key, 65022, ts_ip) + [restart_cmd])
    if r.returncode != 0:
        sys.exit(f"Deploy failed (ssh exit {r.returncode})")

    print(f"\nAlerting detector deployed.")
    print(f"  Detection events → {{job=\"detections\"}} in Loki at http://{ts_ip}:3100")
    print(f"  Logs: DOCKER_HOST=unix:///run/user/<honey-uid>/docker.sock "
          f"docker compose -f {remote_dir}/docker-compose.yml logs -f")


if __name__ == "__main__":
    main()
