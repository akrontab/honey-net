#!/usr/bin/env python3
"""Restores a backup to the live network after reprovisioning.

Catalog restore: uploads catalog.sql + samples/ to the malware-catalog server,
stops the catalog container, replaces the DB, restores sample binaries, then restarts.

Inbox restore (--with-inbox): pushes backed-up inbox files back to each honeypot
server so malware-sender can re-submit them to the catalog.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import REPO_ROOT, load_manifest, load_state
from lib.ssh import DEVNULL, run_ssh, scp_args, ssh_key

PORT = 65022

_CATALOG_DB      = "/var/lib/docker/volumes/malware-catalog_catalog-data/_data/catalog.db"
_CATALOG_SAMPLES = "/var/lib/docker/volumes/malware-catalog_catalog-data/_data/samples"
_COMPOSE_FILE    = "/opt/malware-catalog/docker-compose.yml"


def _scp_file(key, ts_ip, local, remote):
    return subprocess.run(
        ["scp", "-P", str(PORT), "-i", key,
         "-o", "StrictHostKeyChecking=no",
         "-o", f"UserKnownHostsFile={DEVNULL}",
         str(local), f"root@{ts_ip}:{remote}"],
        capture_output=True,
    )


def _scp_dir_up(key, ts_ip, local_dir, remote_dir):
    """Upload contents of local_dir into remote_dir."""
    return subprocess.run(
        scp_args(key, PORT) + [str(local_dir) + "/.", f"root@{ts_ip}:{remote_dir}/"],
        capture_output=True,
    )


def select_backup(path_arg):
    if path_arg:
        p = Path(path_arg)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if not p.exists():
            sys.exit(f"Backup not found: {p}")
        return p

    backups_dir = REPO_ROOT / "backups"
    if not backups_dir.exists():
        sys.exit("No backups/ directory found")

    available = sorted([d for d in backups_dir.iterdir() if d.is_dir()], reverse=True)
    if not available:
        sys.exit("No backups found in backups/")
    if len(available) == 1:
        print(f"Using backup: {available[0].name}")
        return available[0]

    print("\nAvailable backups:")
    for i, d in enumerate(available, 1):
        manifest_path = d / "manifest.json"
        servers = []
        if manifest_path.exists():
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            servers = list(m.get("servers", {}).keys())
        print(f"  [{i}] {d.name}  ({', '.join(servers) or 'unknown'})")
    print()
    choice = input("Select backup: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(available)):
        sys.exit("Invalid selection")
    return available[int(choice) - 1]


def restore_catalog(server, ts_ip, backup_dir):
    key      = ssh_key(server["ssh_key"])
    sql_file = backup_dir / "catalog.sql"

    if not sql_file.exists():
        print("  catalog.sql not found in backup — skipping catalog restore")
        return

    print(f"Restoring catalog ({ts_ip})...")

    print("  Uploading catalog.sql ...", end=" ", flush=True)
    r = _scp_file(key, ts_ip, sql_file, "/tmp/_honey_net_catalog_restore.sql")
    if r.returncode != 0:
        sys.exit("Failed to upload catalog.sql")
    print("ok")

    print("  Stopping malware-catalog container ...", end=" ", flush=True)
    run_ssh(key, PORT, ts_ip,
            f"docker compose -f {_COMPOSE_FILE} stop malware-catalog",
            check=False)
    print("ok")

    print("  Restoring database ...", end=" ", flush=True)
    run_ssh(key, PORT, ts_ip,
            f"rm -f {_CATALOG_DB} && "
            f"sqlite3 {_CATALOG_DB} < /tmp/_honey_net_catalog_restore.sql && "
            f"rm -f /tmp/_honey_net_catalog_restore.sql",
            check=True)
    print("ok")

    samples_dir = backup_dir / "samples"
    sample_files = [f for f in samples_dir.rglob("*") if f.is_file()] if samples_dir.exists() else []
    if sample_files:
        print(f"  Uploading {len(sample_files)} sample(s) ...", end=" ", flush=True)
        run_ssh(key, PORT, ts_ip, f"mkdir -p {_CATALOG_SAMPLES}", check=False)
        r = _scp_dir_up(key, ts_ip, samples_dir, _CATALOG_SAMPLES)
        print("ok" if r.returncode == 0 else "failed (samples not restored)")
    else:
        print("  No samples in backup.")

    print("  Starting malware-catalog container ...", end=" ", flush=True)
    run_ssh(key, PORT, ts_ip,
            f"docker compose -f {_COMPOSE_FILE} start malware-catalog",
            check=False)
    print("ok")

    print("  Catalog restored.")


def restore_inbox(server, ts_ip, backup_dir):
    name      = server["name"]
    key       = ssh_key(server["ssh_key"])
    inbox_dir = backup_dir / "inbox"

    files = [f for f in inbox_dir.rglob("*") if f.is_file()] if inbox_dir.exists() else []
    if not files:
        print(f"  {name}: no inbox files in backup — skipping.")
        return

    print(f"Restoring inbox for {name} ({ts_ip}): {len(files)} file(s) ...", end=" ", flush=True)
    r = _scp_dir_up(key, ts_ip, inbox_dir, f"/opt/{name}/inbox")
    print("ok" if r.returncode == 0 else "failed")


def main():
    parser = argparse.ArgumentParser(
        description="Restore a backup to the live network after reprovisioning.",
    )
    parser.add_argument("--backup", "-b", metavar="PATH",
                        help="Path to backup dir (default: prompt from backups/)")
    parser.add_argument("--no-catalog", action="store_true",
                        help="Skip catalog restore")
    parser.add_argument("--with-inbox", action="store_true",
                        help="Also restore honeypot inbox samples (re-triggers malware-sender)")
    args = parser.parse_args()

    backup_dir = select_backup(args.backup)
    manifest_path = backup_dir / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"Backup:   {m['timestamp']}")
        print(f"Contains: {', '.join(m['servers'].keys())}")
    else:
        print(f"Backup: {backup_dir.name}")

    servers = load_manifest()
    state   = load_state()

    # Catalog
    if not args.no_catalog:
        catalog_backup = backup_dir / "malware-catalog"
        if catalog_backup.exists():
            catalog = next((s for s in servers if s["name"] == "malware-catalog"), None)
            if catalog:
                entry = state.get("malware-catalog", {})
                ts_ip = entry.get("tailscale_ip")
                if ts_ip:
                    print()
                    restore_catalog(catalog, ts_ip, catalog_backup)
                else:
                    print("malware-catalog: no Tailscale IP in state.json — skipping", file=sys.stderr)
        else:
            print("No catalog backup found in this backup dir.")

    # Honeypot inboxes (opt-in)
    if args.with_inbox:
        honeypots = [s for s in servers if s["type"] == "honeypot"]
        print()
        for server in honeypots:
            name  = server["name"]
            entry = state.get(name, {})
            ts_ip = entry.get("tailscale_ip")
            if not ts_ip:
                print(f"  {name}: no Tailscale IP — skipping inbox restore", file=sys.stderr)
                continue
            server_backup = backup_dir / name
            if not server_backup.exists():
                print(f"  {name}: no backup dir found — skipping")
                continue
            restore_inbox(server, ts_ip, server_backup)

    print("\nDone.")


if __name__ == "__main__":
    main()
