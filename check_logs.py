#!/usr/bin/env python3
"""Check log stream freshness in Loki for all honeypots."""

import argparse
import sys
import time
from datetime import datetime, timezone

import requests

from lib.color import bold, gray, green, red, yellow
from lib.config import load_manifest, load_state
from lib.server import select_server

WARN_SECS = 30 * 60   # 30 minutes — yellow
ERR_SECS  = 2 * 3600  # 2 hours    — red


def _loki_ready(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/ready", timeout=5)
        return r.status_code == 200
    except requests.exceptions.ConnectionError:
        return False


def _job_values(base_url: str) -> list[str]:
    r = requests.get(f"{base_url}/loki/api/v1/label/job/values", timeout=10)
    r.raise_for_status()
    return sorted(r.json().get("data", []))


def _host_values(base_url: str) -> list[str]:
    r = requests.get(f"{base_url}/loki/api/v1/label/host/values", timeout=10)
    r.raise_for_status()
    return sorted(r.json().get("data", []))


def _latest(base_url: str, logql: str, lookback_ns: int, now_ns: int):
    """Return (timestamp_ns, message) of the most recent matching entry, or None."""
    params = {
        "query":     logql,
        "start":     str(lookback_ns),
        "end":       str(now_ns),
        "limit":     "1",
        "direction": "backward",
    }
    r = requests.get(f"{base_url}/loki/api/v1/query_range", params=params, timeout=15)
    r.raise_for_status()
    results = r.json().get("data", {}).get("result", [])
    if not results:
        return None
    values = results[0].get("values", [])
    if not values:
        return None
    return int(values[0][0]), values[0][1]


def _age_str(age_sec: float) -> str:
    if age_sec < 60:
        return f"{int(age_sec)}s ago"
    if age_sec < 3600:
        return f"{int(age_sec / 60)}m ago"
    return f"{int(age_sec / 3600)}h ago"


def _colorize_age(age_sec: float, text: str) -> str:
    if age_sec < WARN_SECS:
        return green(text)
    if age_sec < ERR_SECS:
        return yellow(text)
    return red(text)


def _status(age_sec: float) -> str:
    if age_sec < WARN_SECS:
        return green("OK")
    if age_sec < ERR_SECS:
        return yellow("STALE")
    return red("STALE")


def _print_row(job: str, dt_str: str, age: str, status: str, indent: str = ""):
    COL_JOB = 18
    COL_TS  = 22
    COL_AGE = 12
    print(f"{indent}{job:<{COL_JOB}} {dt_str:<{COL_TS}} {age:<{COL_AGE}} {status}")


def main():
    parser = argparse.ArgumentParser(
        description="Check log stream freshness in Loki for all honeypot streams.",
    )
    parser.add_argument(
        "--loki-host", metavar="IP",
        help="Tailscale IP of the log-stack server (skips auto-detect from state.json)",
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Lookback window in hours when searching for recent logs (default: 24)",
    )
    parser.add_argument(
        "--by-host", action="store_true",
        help="Show per-honeypot breakdown within each job stream",
    )
    args = parser.parse_args()

    if args.loki_host:
        loki_host = args.loki_host
    else:
        servers = load_manifest()
        state   = load_state()
        server  = select_server(
            servers, state,
            filter_fn=lambda s: s["type"] == "backend",
            prompt="Select a log-stack server",
        )
        name      = server["name"]
        loki_host = state.get(name, {}).get("tailscale_ip")
        if not loki_host:
            sys.exit(f"No Tailscale IP for '{name}' in state.json — run sync_ips.py")
        print(f"Loki host: {loki_host}  ({name})\n")

    base_url = f"http://{loki_host}:3100"

    if not _loki_ready(base_url):
        sys.exit(
            f"{red('Cannot reach Loki')} at {loki_host}:3100\n\n"
            "Checklist:\n"
            f"  1. Tailscale running locally:       tailscale status\n"
            f"  2. log-stack host is reachable:     tailscale ping {loki_host}\n"
            f"  3. Loki container is running:       docker compose -f /opt/log-stack/docker-compose.yml ps\n"
            f"  4. Loki bound to correct interface: ss -tlnp | grep 3100  (on server)\n"
        )

    print(f"{green('Loki ready')} — {base_url}\n")

    jobs = _job_values(base_url)
    if not jobs:
        print(yellow("No job label values found in Loki — no logs have been ingested yet."))
        print("\nPossible causes:")
        print("  - Vector is not running on the honeypot (check: docker compose ps)")
        print("  - LOKI_HOST is unset or wrong in the honeypot .env")
        print("  - Logs have not been written yet (honeypot services just started)")
        return

    now_ns      = time.time_ns()
    lookback_ns = now_ns - args.hours * 3600 * 1_000_000_000

    hosts = _host_values(base_url) if args.by_host else []

    print(bold(f"{'Job':<18} {'Last log (UTC)':<22} {'Age':<12} Status"))
    print(gray("─" * 62))

    any_bad = False
    for job in jobs:
        entry = _latest(base_url, f'{{job="{job}"}}', lookback_ns, now_ns)

        if entry is None:
            _print_row(
                job,
                "(none in window)",
                f"> {args.hours}h",
                red("NO LOGS"),
            )
            any_bad = True
        else:
            ts_ns, _msg = entry
            age_sec     = (now_ns - ts_ns) / 1_000_000_000
            dt_str      = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            age         = _age_str(age_sec)
            status      = _status(age_sec)
            if age_sec >= WARN_SECS:
                any_bad = True
            _print_row(job, dt_str, _colorize_age(age_sec, age), status)

            if args.by_host:
                for host in hosts:
                    h_entry = _latest(base_url, f'{{job="{job}",host="{host}"}}', lookback_ns, now_ns)
                    if h_entry is None:
                        continue
                    h_ts_ns, _ = h_entry
                    h_age_sec  = (now_ns - h_ts_ns) / 1_000_000_000
                    h_dt_str   = datetime.fromtimestamp(h_ts_ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    h_age      = _age_str(h_age_sec)
                    h_status   = _status(h_age_sec)
                    _print_row(
                        f"  └─ {host}",
                        h_dt_str,
                        _colorize_age(h_age_sec, h_age),
                        h_status,
                    )

    print()
    if any_bad:
        print(yellow("One or more streams are stale or missing.\n"))
        print("Possible causes:")
        print("  - Vector is not running or restarted:  docker compose -f /opt/<server>/docker-compose.yml logs vector")
        print("  - LOKI_HOST env var is wrong:          docker compose -f /opt/<server>/docker-compose.yml exec vector env | grep LOKI")
        print("  - Log file not found by Vector:        docker compose -f /opt/<server>/docker-compose.yml exec vector vector top")
        print("  - Honeypot service not writing logs:   check its own container logs")
        print()
        print(gray("Note: 'malware' stream is only active when Cowrie downloads are analyzed — silence is normal."))
    else:
        print(green("All streams are flowing normally."))


if __name__ == "__main__":
    main()
