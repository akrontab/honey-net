"""
Honey-net alerting detector.

Polls Loki and the malware-catalog, evaluates detection rules, and appends
detection events as JSONL to LOG_FILE.  Vector tails that file and ships
them to {job="detections"} in Loki.

Env vars:
  LOKI_URL          Loki HTTP endpoint (default: http://loki:3100)
  CATALOG_URL       Malware-catalog HTTP endpoint (optional; needed for new-sample rule)
  OPERATORS_FILE    Path to operators.json (default: /config/operators.json)
  HONEY_NET_FILE    Path to honey-net.json (default: /config/honey-net.json)
  POLL_SECS         Poll interval in seconds (default: 60)
  SENSOR_DARK_MINS  Sensor-dark threshold in minutes (default: 10)
  BURST_THRESHOLD   Login attempts per IP per poll interval to trigger burst alert (default: 50)
  LOG_FILE          Output path for detection events (default: /logs/detections.json)
"""
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

LOKI_URL         = os.getenv("LOKI_URL",         "http://loki:3100").rstrip("/")
CATALOG_URL      = os.getenv("CATALOG_URL",       "").rstrip("/")
OPERATORS_FILE   = Path(os.getenv("OPERATORS_FILE", "/config/operators.json"))
HONEY_NET_FILE   = Path(os.getenv("HONEY_NET_FILE", "/config/honey-net.json"))
POLL_SECS        = int(os.getenv("POLL_SECS",        "60"))
SENSOR_DARK_MINS = int(os.getenv("SENSOR_DARK_MINS", "10"))
BURST_THRESHOLD  = int(os.getenv("BURST_THRESHOLD",  "50"))
LOG_FILE         = Path(os.getenv("LOG_FILE",         "/logs/detections.json"))

_AUTH_ACCEPTED_RE = re.compile(r"Accepted (?:publickey|password) for \S+ from (\S+) port")

# Dedup: suppress (rule_id, entity) pairs that fired within the last hour.
_DEDUP: dict[tuple[str, str], datetime] = {}
_DEDUP_WINDOW = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(msg: str) -> None:
    print(f"[{_now().isoformat()}] {msg}", flush=True)


def _ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1e9)


def _emit(event: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event) + "\n")
    _log(f"DETECTION rule={event['rule_id']} severity={event['severity']} entity={event['entity']}")


def _dedup_ok(rule_id: str, entity: str) -> bool:
    key = (rule_id, entity)
    last = _DEDUP.get(key)
    if last is not None and (_now() - last) < _DEDUP_WINDOW:
        return False
    _DEDUP[key] = _now()
    return True


def detect(rule_id: str, severity: str, category: str, entity: str,
           summary: str, context: dict, dedup: bool = False) -> None:
    if dedup and not _dedup_ok(rule_id, entity):
        return
    _emit({
        "timestamp": _now().isoformat(),
        "rule_id":   rule_id,
        "severity":  severity,
        "category":  category,
        "entity":    entity,
        "summary":   summary,
        "context":   context,
    })


# ── Config ────────────────────────────────────────────────────────────────────

def _load_operator_ips() -> set[str]:
    try:
        return set(json.loads(OPERATORS_FILE.read_text("utf-8")).get("operator_ips", []))
    except Exception as e:
        _log(f"WARNING operators.json unreadable: {e}")
        return set()


def _load_honeypot_names() -> list[str]:
    try:
        servers = json.loads(HONEY_NET_FILE.read_text("utf-8"))
        seen: set[str] = set()
        names: list[str] = []
        for s in servers:
            for hp in s.get("honeypots", []):
                if hp not in seen:
                    seen.add(hp)
                    names.append(hp)
        return names
    except Exception as e:
        _log(f"WARNING honey-net.json unreadable: {e}")
        return []


# ── Loki client ───────────────────────────────────────────────────────────────

def _loki_query_range(logql: str, start: datetime, end: datetime,
                      limit: int = 500) -> list[dict]:
    """Return log entries in [start, end]; JSON lines are merged into the entry dict."""
    try:
        r = requests.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": str(_ns(start)),
                "end":   str(_ns(end)),
                "limit": str(limit),
                "direction": "forward",
            },
            timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        _log(f"Loki query error: {e}")
        return []

    entries = []
    for stream in r.json().get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for _, line in stream.get("values", []):
            entry: dict = {"_raw": line, "_stream": labels}
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    entry.update(parsed)
            except (json.JSONDecodeError, ValueError):
                pass
            entries.append(entry)
    return entries


def _loki_instant_metric(logql: str) -> list[dict]:
    """Run an instant scalar metric query (e.g. sum(count_over_time(...)))."""
    try:
        r = requests.get(
            f"{LOKI_URL}/loki/api/v1/query",
            params={"query": logql, "time": str(_ns(_now()))},
            timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        _log(f"Loki metric query error: {e}")
        return []
    return r.json().get("data", {}).get("result", [])


# ── Rule class 1 — Security-model violations ─────────────────────────────────

def _check_real_ssh_auth(start: datetime, end: datetime,
                         operator_ips: set[str]) -> None:
    """Fire when a non-operator IP successfully authenticates on :65022."""
    entries = _loki_query_range(
        '{job="auth"} |~ "Accepted (publickey|password) for"', start, end
    )
    for entry in entries:
        m = _AUTH_ACCEPTED_RE.search(entry["_raw"])
        if not m:
            continue
        src_ip = m.group(1)
        if src_ip in operator_ips:
            continue
        host = entry["_stream"].get("host", "unknown")
        detect(
            rule_id="real-ssh-auth-success",
            severity="page",
            category="security-model",
            entity=src_ip,
            summary=f"Successful auth on :65022 from non-operator IP {src_ip} (host: {host})",
            context={"src_ip": src_ip, "host": host},
            dedup=True,
        )


def _check_sensor_dark(honeypots: list[str]) -> None:
    """Fire when a known honeypot has zero events in the last SENSOR_DARK_MINS."""
    for hp in honeypots:
        result = _loki_instant_metric(
            f'sum(count_over_time({{job="events", honeypot="{hp}"}}[{SENSOR_DARK_MINS}m]))'
        )
        count = sum(int(float(r["value"][1])) for r in result) if result else 0
        if count == 0:
            detect(
                rule_id="sensor-dark",
                severity="page",
                category="security-model",
                entity=hp,
                summary=f"Sensor '{hp}' dark — no events in {SENSOR_DARK_MINS} min",
                context={"honeypot": hp, "window_mins": SENSOR_DARK_MINS},
                dedup=True,
            )


# ── Rule class 2 — Sample novelty ────────────────────────────────────────────

def _check_new_samples(start: datetime, end: datetime) -> None:
    """Fire once per new sample ingested into the catalog."""
    entries = _loki_query_range(
        '{job="catalog"} | json | event = "new_sample"', start, end
    )
    for entry in entries:
        sha = entry.get("sha256", "unknown")
        detect(
            rule_id="new-sample",
            severity="notice",
            category="novelty",
            entity=sha[:16],
            summary=f"New malware sample ingested: {sha[:16]}…",
            context={"sha256": sha, "md5": entry.get("md5"), "size": entry.get("size")},
        )


# ── Rule class 3 — Threshold (exercises dedup mechanism) ─────────────────────

def _check_credential_burst(start: datetime, end: datetime) -> None:
    """Fire when a single IP exceeds BURST_THRESHOLD login attempts in one poll interval."""
    entries = _loki_query_range(
        '{job="events"} | json | event_type = "login"', start, end, limit=2000
    )
    counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        ip = entry.get("src_ip")
        if ip:
            counts[ip] += 1
    for ip, count in counts.items():
        if count >= BURST_THRESHOLD:
            detect(
                rule_id="credential-burst",
                severity="notice",
                category="threshold",
                entity=ip,
                summary=f"{ip} made {count} login attempts in {POLL_SECS}s (threshold: {BURST_THRESHOLD})",
                context={"src_ip": ip, "count": count, "window_secs": POLL_SECS},
                dedup=True,
            )


# ── Main loop ─────────────────────────────────────────────────────────────────

def _wait_for_loki() -> None:
    for _ in range(12):
        try:
            if requests.get(f"{LOKI_URL}/ready", timeout=5).status_code == 200:
                return
        except requests.RequestException:
            pass
        _log("waiting for Loki...")
        time.sleep(10)
    _log("WARNING: Loki not ready after 2 min — proceeding anyway")


def main() -> None:
    _log(
        f"detector started  loki={LOKI_URL}  poll={POLL_SECS}s  "
        f"dark={SENSOR_DARK_MINS}m  burst={BURST_THRESHOLD}"
    )
    _wait_for_loki()
    last_run = _now() - timedelta(seconds=POLL_SECS)

    while True:
        now   = _now()
        start = last_run
        end   = now

        op_ips    = _load_operator_ips()
        honeypots = _load_honeypot_names()

        for fn, args in [
            (_check_real_ssh_auth,    (start, end, op_ips)),
            (_check_sensor_dark,      (honeypots,)),
            (_check_new_samples,      (start, end)),
            (_check_credential_burst, (start, end)),
        ]:
            try:
                fn(*args)
            except Exception as e:
                _log(f"rule error in {fn.__name__}: {e}")

        last_run = now
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
