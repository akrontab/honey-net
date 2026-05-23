#!/usr/bin/env python3
"""Pulls log files from a honeypot server to logs/<server-name>/ locally."""

import argparse
import subprocess
import sys
from pathlib import Path

from lib.config import REPO_ROOT, load_manifest, load_state
from lib.server import select_server
from lib.ssh import DEVNULL, ssh_key


def load_honeypot_logs(hp: str) -> list[dict]:
    """Return log entries from honey-pots/<hp>/deploy/logs.json, or [] if absent."""
    path = REPO_ROOT / "honey-pots" / hp / "deploy" / "logs.json"
    if not path.exists():
        return []
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="Pull honeypot log files to logs/<server>/ via Tailscale.",
    )
    parser.add_argument("--server", "-s", metavar="NAME", help="Server name from honey-net.json")
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()

    server = select_server(
        servers, state,
        name_arg=args.server,
        filter_fn=lambda s: s["type"] == "honeypot",
        prompt="Select a honeypot server to pull logs from",
    )

    if server["type"] != "honeypot":
        sys.exit(f"'{server['name']}' is a {server['type']} server — get_logs.py only applies to honeypots")

    name   = server["name"]
    key    = ssh_key(server["ssh_key"])
    entry  = state.get(name, {})
    ts_ip  = entry.get("tailscale_ip")

    if not ts_ip:
        sys.exit(f"No Tailscale IP for '{name}' in state.json — run sync_ips.py (Tailscale must be active)")

    local_dir = REPO_ROOT / "logs" / name
    local_dir.mkdir(parents=True, exist_ok=True)

    print(f"Pulling logs from {name} ({ts_ip})...\n")

    pulled, failed = 0, 0
    for hp in server["honeypots"]:
        log_entries = load_honeypot_logs(hp)
        pullable = [e for e in log_entries if e.get("log_file")]

        if not pullable:
            print(f"  Warning: no log_file declared for '{hp}' in logs.json — skipping", file=sys.stderr)
            continue

        for entry in pullable:
            log_file    = entry["log_file"]
            remote_path = f"/opt/{name}/{hp}/{entry['host']}/{log_file}"
            local_file  = local_dir / f"{hp}.json"

            print(f"  {hp}/{log_file} -> {local_file}")
            r = subprocess.run([
                "scp", "-P", "65022", "-i", key,
                "-o", "StrictHostKeyChecking=no",
                "-o", f"UserKnownHostsFile={DEVNULL}",
                f"root@{ts_ip}:{remote_path}",
                str(local_file),
            ])

            if r.returncode == 0:
                lines = sum(1 for _ in local_file.open(encoding="utf-8", errors="replace"))
                print(f"    {lines} events")
                pulled += 1
            else:
                print(f"    Warning: failed (scp exit {r.returncode}) — log file may not exist yet",
                      file=sys.stderr)
                failed += 1

    print()
    if pulled:
        print(f"Logs saved to logs/{name}/")
    if failed:
        print(f"{failed} log(s) could not be pulled.")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
