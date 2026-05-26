#!/usr/bin/env python3
"""Per-IP connection rollup for the MySQL honeypot log."""

import argparse
import contextlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.color import bold, gray, green, red, yellow, _enable_ansi
import lib.color as _color_mod

_enable_ansi()

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "logs" / "mysql-ssh" / "mysql.json"


def _parse_log(path: Path) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def _rollup(events: list[dict]) -> dict[str, dict]:
    ips: dict[str, dict] = defaultdict(lambda: {
        "connections": 0,
        "logins": 0,
        "usernames": set(),
        "queries": 0,
        "unique_queries": {},  # query -> first-seen timestamp, insertion-ordered
        "sessions": set(),
        "first_seen": None,
        "last_seen": None,
    })

    for ev in events:
        ip = ev.get("src_ip")
        if not ip:
            continue

        r = ips[ip]
        ts = ev.get("timestamp", "")
        if ts:
            if r["first_seen"] is None or ts < r["first_seen"]:
                r["first_seen"] = ts
            if r["last_seen"] is None or ts > r["last_seen"]:
                r["last_seen"] = ts

        kind = ev.get("event")
        if kind == "connect":
            r["connections"] += 1
            session_key = (ev.get("src_port"), ev.get("conn_id"))
            r["sessions"].add(session_key)
        elif kind == "login":
            r["logins"] += 1
            u = ev.get("username")
            if u:
                r["usernames"].add(u)
        elif kind == "query":
            r["queries"] += 1
            q = ev.get("query", "").strip()
            if q and q not in r["unique_queries"]:
                r["unique_queries"][q] = ts

    return dict(ips)


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts[:16]


def _print_table(rollup: dict[str, dict], top: int | None, truncate: bool = True) -> None:
    rows = sorted(rollup.items(), key=lambda x: x[1]["connections"], reverse=True)
    if top:
        rows = rows[:top]

    C_IP    = 18
    C_CONN  =  7
    C_LOGIN =  7
    C_QUERY =  7
    C_USER  = 26
    C_TS    = 17

    header = (
        f"{'IP':<{C_IP}} {'Conns':>{C_CONN}} {'Logins':>{C_LOGIN}} "
        f"{'Queries':>{C_QUERY}}  {'Usernames':<{C_USER}} {'First seen':<{C_TS}} Last seen"
    )
    print(bold(header))
    print(gray("-" * (C_IP + C_CONN + C_LOGIN + C_QUERY + C_USER + C_TS * 2 + 10)))

    for ip, r in rows:
        usernames = ", ".join(sorted(r["usernames"])) or gray("(none)")
        if truncate and len(usernames) > C_USER:
            usernames = usernames[: C_USER - 3] + "..."
        queries_col = r["queries"]
        conn_col    = r["connections"]
        login_col   = r["logins"]

        conn_str  = green(str(conn_col))  if conn_col  > 0 else gray("0")
        login_str = yellow(str(login_col)) if login_col > 0 else gray("0")
        q_str     = red(str(queries_col))  if queries_col > 0 else gray("0")

        print(
            f"{ip:<{C_IP}} {conn_str:>{C_CONN + 9}} {login_str:>{C_LOGIN + 9}} "
            f"{q_str:>{C_QUERY + 9}}  {usernames:<{C_USER}} "
            f"{_fmt_ts(r['first_seen']):<{C_TS}} {_fmt_ts(r['last_seen'])}"
        )


def _print_detail(ip: str, r: dict, truncate: bool = True) -> None:
    print(bold(f"\n-- {ip} --"))
    print(f"  Connections : {r['connections']}")
    print(f"  Logins      : {r['logins']}")
    print(f"  Usernames   : {', '.join(sorted(r['usernames'])) or '(none)'}")
    print(f"  Queries     : {r['queries']}  ({len(r['unique_queries'])} unique)")
    print(f"  First seen  : {_fmt_ts(r['first_seen'])}")
    print(f"  Last seen   : {_fmt_ts(r['last_seen'])}")

    if r["unique_queries"]:
        print(f"\n  Unique queries ({len(r['unique_queries'])}, chronological):")
        for q in r["unique_queries"]:
            line = q[:120] + ("..." if truncate and len(q) > 120 else "") if truncate else q
            print(f"    {gray('-')} {line}")


def main():
    parser = argparse.ArgumentParser(
        description="Per-IP rollup of MySQL honeypot connection activity.",
    )
    parser.add_argument(
        "--log", metavar="FILE", type=Path, default=DEFAULT_LOG,
        help=f"Path to mysql.json log (default: {DEFAULT_LOG})",
    )
    parser.add_argument(
        "--top", metavar="N", type=int, default=None,
        help="Show only the top N IPs by connection count",
    )
    parser.add_argument(
        "--ip", metavar="ADDR",
        help="Show detailed breakdown for a single IP",
    )
    parser.add_argument(
        "--queries", action="store_true",
        help="Show unique queries for every IP in the table (implies verbose output)",
    )
    parser.add_argument(
        "--output", "-o", metavar="FILE", type=Path, default=None,
        help="Write output to a file instead of stdout (colors stripped automatically)",
    )
    args = parser.parse_args()

    if not args.log.exists():
        sys.exit(f"Log file not found: {args.log}\n  Run: python honey.py logs")

    print(f"{gray('Reading')} {args.log}  ...", end="", flush=True)
    events = _parse_log(args.log)
    rollup = _rollup(events)
    print(f"\r{len(events):,} events  {len(rollup):,} unique IPs\n")

    out_file = None
    truncate = True
    if args.output:
        out_file = open(args.output, "w", encoding="utf-8", newline="\n")
        _color_mod._COLOR = False
        truncate = False

    with contextlib.redirect_stdout(out_file or sys.stdout):
        if args.ip:
            if args.ip not in rollup:
                sys.exit(f"IP {args.ip!r} not found in log.")
            _print_detail(args.ip, rollup[args.ip], truncate=truncate)
        else:
            _print_table(rollup, args.top, truncate=truncate)

            if args.queries:
                for ip, r in sorted(rollup.items(), key=lambda x: x[1]["connections"], reverse=True):
                    if r["unique_queries"]:
                        _print_detail(ip, r, truncate=truncate)

            total_conns   = sum(r["connections"]   for r in rollup.values())
            total_logins  = sum(r["logins"]        for r in rollup.values())
            total_queries = sum(r["queries"]       for r in rollup.values())
            print(f"\nTotals: {total_conns:,} connections  {total_logins:,} logins  {total_queries:,} queries  {len(rollup):,} unique IPs")

    if out_file:
        out_file.close()
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
