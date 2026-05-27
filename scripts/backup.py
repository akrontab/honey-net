#!/usr/bin/env python3
"""Backs up honeypot logs, inbox samples, and the malware catalog to backups/<timestamp>/."""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import REPO_ROOT, load_manifest, load_state
from lib.ssh import DEVNULL, run_ssh, scp_args, ssh_key

PORT = 65022

_CATALOG_DB      = "/var/lib/docker/volumes/malware-catalog_catalog-data/_data/catalog.db"
_CATALOG_SAMPLES = "/var/lib/docker/volumes/malware-catalog_catalog-data/_data/samples"
_CATALOG_LOG     = "/var/lib/docker/volumes/malware-catalog_catalog-logs/_data/submissions.json"


def _scp_file(key, ts_ip, remote, local):
    return subprocess.run(
        ["scp", "-P", str(PORT), "-i", key,
         "-o", "StrictHostKeyChecking=no",
         "-o", f"UserKnownHostsFile={DEVNULL}",
         f"root@{ts_ip}:{remote}", str(local)],
        capture_output=True,
    )


def _scp_dir_down(key, ts_ip, remote_dir, local_dir):
    """Download contents of remote_dir into local_dir."""
    return subprocess.run(
        scp_args(key, PORT) + [f"root@{ts_ip}:{remote_dir}/.", str(local_dir)],
        capture_output=True,
    )


def backup_honeypot(server, ts_ip, out_dir):
    name = server["name"]
    key  = ssh_key(server["ssh_key"])

    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  {name} ({ts_ip})")

    log_stats = {}
    for hp in server["honeypots"]:
        remote = f"/opt/{name}/{hp}/volumes/logs/{hp}.json"
        local  = logs_dir / f"{hp}.json"
        print(f"    logs/{hp}.json ...", end=" ", flush=True)
        r = _scp_file(key, ts_ip, remote, local)
        if r.returncode == 0:
            lines = sum(1 for _ in local.open(encoding="utf-8", errors="replace"))
            print(f"{lines:,} events")
            log_stats[hp] = lines
        else:
            print("not found (skipped)")

    inbox_dir = out_dir / "inbox"
    inbox_dir.mkdir(exist_ok=True)
    print(f"    inbox/ ...", end=" ", flush=True)
    r = _scp_dir_down(key, ts_ip, f"/opt/{name}/inbox", inbox_dir)
    inbox_files = sum(1 for f in inbox_dir.rglob("*") if f.is_file())
    if r.returncode == 0 and inbox_files:
        print(f"{inbox_files} files")
    else:
        print("empty (skipped)")
        inbox_files = 0

    return {"logs": log_stats, "inbox_files": inbox_files}


def backup_catalog(server, ts_ip, out_dir):
    key = ssh_key(server["ssh_key"])
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  malware-catalog ({ts_ip})")

    stats = {}

    # Dump SQLite DB via SSH then pull the file
    print(f"    catalog.sql ...", end=" ", flush=True)
    run_ssh(key, PORT, ts_ip,
            f"sqlite3 {_CATALOG_DB} .dump > /tmp/_honey_net_catalog.sql",
            check=False)
    local_sql = out_dir / "catalog.sql"
    r = _scp_file(key, ts_ip, "/tmp/_honey_net_catalog.sql", local_sql)
    run_ssh(key, PORT, ts_ip, "rm -f /tmp/_honey_net_catalog.sql", check=False)
    if r.returncode == 0:
        size = local_sql.stat().st_size
        print(f"{size:,} bytes")
        stats["db_size_bytes"] = size
    else:
        print("failed")

    # Pull sample binaries
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(exist_ok=True)
    print(f"    samples/ ...", end=" ", flush=True)
    r = _scp_dir_down(key, ts_ip, _CATALOG_SAMPLES, samples_dir)
    count = sum(1 for f in samples_dir.rglob("*") if f.is_file())
    if count:
        print(f"{count} files")
    else:
        print("empty (skipped)")
    stats["samples"] = count

    # Pull audit log
    print(f"    submissions.json ...", end=" ", flush=True)
    local_log = out_dir / "submissions.json"
    r = _scp_file(key, ts_ip, _CATALOG_LOG, local_log)
    if r.returncode == 0:
        events = sum(1 for _ in local_log.open(encoding="utf-8", errors="replace"))
        print(f"{events:,} events")
        stats["audit_events"] = events
    else:
        print("failed (skipped)")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Back up honeypot logs, inbox, and malware catalog to backups/<timestamp>/.",
    )
    parser.add_argument("--server", "-s", metavar="NAME",
                        help="Honeypot server to back up (default: all honeypots)")
    parser.add_argument("--no-catalog", action="store_true",
                        help="Skip malware catalog backup")
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()

    ts          = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    backup_root = REPO_ROOT / "backups" / ts
    backup_root.mkdir(parents=True, exist_ok=True)

    print(f"Backup: backups/{ts}/")

    manifest = {"timestamp": ts, "servers": {}}

    # Honeypot servers
    honeypots = [s for s in servers if s["type"] == "honeypot"]
    if args.server:
        honeypots = [s for s in honeypots if s["name"] == args.server]
        if not honeypots:
            sys.exit(f"No honeypot server named '{args.server}' in honey-net.json")

    if honeypots:
        print("\nHoneypots:")
    for server in honeypots:
        name  = server["name"]
        entry = state.get(name, {})
        ts_ip = entry.get("tailscale_ip")
        if not ts_ip:
            print(f"  {name}: no Tailscale IP in state.json — skipping", file=sys.stderr)
            continue
        stats = backup_honeypot(server, ts_ip, backup_root / name)
        manifest["servers"][name] = stats

    # Malware catalog
    if not args.no_catalog:
        catalog = next((s for s in servers if s["name"] == "malware-catalog"), None)
        if catalog:
            entry = state.get("malware-catalog", {})
            ts_ip = entry.get("tailscale_ip")
            if ts_ip:
                print("\nCatalog:")
                stats = backup_catalog(catalog, ts_ip, backup_root / "malware-catalog")
                manifest["servers"]["malware-catalog"] = stats
            else:
                print("malware-catalog: no Tailscale IP in state.json — skipping", file=sys.stderr)

    manifest_path = backup_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"\nDone. Backup saved to backups/{ts}/")


if __name__ == "__main__":
    main()
