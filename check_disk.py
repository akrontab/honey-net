#!/usr/bin/env python3
"""Check disk usage on honey-net servers."""

import argparse
import sys

from lib.color import bold, gray, green, red, yellow
from lib.config import load_manifest, load_state
from lib.ssh import run_ssh, ssh_key

WARN_PCT  = 60
ERR_PCT   = 80
NANODE_GB = 25
BAR_WIDTH = 20


def _pct_color(pct: int, text: str) -> str:
    if pct < WARN_PCT:
        return green(text)
    if pct < ERR_PCT:
        return yellow(text)
    return red(text)


def _bar(pct: int) -> str:
    filled = round(BAR_WIDTH * pct / 100)
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    return _pct_color(pct, bar)


def _parse_df(output: str):
    """Return (size, used, avail, pct_int) from 'df -h /' output, or None."""
    lines = output.strip().splitlines()
    if len(lines) < 2:
        return None
    parts = lines[1].split()
    # Filesystem  Size  Used  Avail  Use%  Mounted
    if len(parts) < 5:
        return None
    try:
        return parts[1], parts[2], parts[3], int(parts[4].rstrip("%"))
    except ValueError:
        return None


def _check_server(server: dict, state: dict) -> int | None:
    """Print disk report for one server. Returns disk-used pct, or None on failure."""
    name  = server["name"]
    entry = state.get(name, {})
    ip    = entry.get("tailscale_ip")

    if not ip:
        print(f"  {red('SKIP')} — no Tailscale IP in state.json (run sync_ips.py)")
        return None

    key = ssh_key(server["ssh_key"])

    df_out = run_ssh(key, 65022, ip, "df -h /", capture=True)
    if df_out is None:
        print(f"  {red('SSH failed')} — is Tailscale running? Is the server up?")
        return None

    parsed = _parse_df(df_out)
    if parsed is None:
        print(f"  {red('Cannot parse df output')}: {df_out!r}")
        return None

    size, used, avail, pct = parsed
    pct_str = _pct_color(pct, f"{pct:3d}%")
    print(f"  Root:    {used:>5} / {size:<5}  ({pct_str})  [{_bar(pct)}]  {avail} free")

    vol_cmd = (
        "du -sh /var/lib/docker/volumes/*/ 2>/dev/null | sort -rh | head -8 || true"
    )
    vol_out = run_ssh(key, 65022, ip, vol_cmd, capture=True)
    if vol_out:
        print(f"  {gray('Docker volumes:')}")
        for line in vol_out.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                vol_size, vol_path = parts
                vol_name = vol_path.rstrip("/").rsplit("/", 1)[-1]
                print(f"    {gray(f'{vol_name:<40}')} {vol_size}")

    docker_out = run_ssh(key, 65022, ip, "du -sh /var/lib/docker/ 2>/dev/null || true", capture=True)
    if docker_out:
        docker_total = docker_out.split(None, 1)[0]
        print(f"  {gray('Docker total:')} {docker_total}")

    return pct


def main():
    parser = argparse.ArgumentParser(
        description=f"Check disk usage on honey-net servers (Nanode limit: {NANODE_GB} GB).",
    )
    parser.add_argument(
        "--server", "-s", metavar="NAME",
        help="Check only this server (default: all servers)",
    )
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()

    if args.server:
        targets = [s for s in servers if s["name"] == args.server]
        if not targets:
            sys.exit(f"Server '{args.server}' not found in honey-net.json")
    else:
        targets = servers

    print(bold(f"Disk usage  (Nanode limit: {NANODE_GB} GB)\n"))

    pcts: list[int] = []
    for server in targets:
        name  = server["name"]
        entry = state.get(name, {})
        ts_ip = entry.get("tailscale_ip") or "(no Tailscale IP)"
        print(bold(name) + gray(f"  {ts_ip}"))
        pct = _check_server(server, state)
        if pct is not None:
            pcts.append(pct)
        print()

    if any(p >= WARN_PCT for p in pcts):
        print(yellow("One or more servers are above 60% disk usage."))
        print()
        print("To free space on log-stack:")
        print("  docker system prune -f")
        print("  cat /opt/log-stack/loki/loki-config.yml | grep -A5 retention")
    elif pcts:
        print(green("All servers have healthy disk usage."))


if __name__ == "__main__":
    main()
