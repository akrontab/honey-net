#!/usr/bin/env python3
"""
SMB honeypot — listens on ports 139 and 445, logs connection and NTLM
authentication events as newline-delimited JSON.

Log format per event:
  connection  {"timestamp":..., "type":"connection",  "src_host":"1.2.3.4", "src_port":54321, "dst_port":445, "protocol":"smb"}
  credentials {"timestamp":..., "type":"credentials", "src_host":null, "login":"DOMAIN\\user", "password":"<NTLMv2 hash|null>", "protocol":"smb"}
"""

import json
import logging
import os
import re
import signal
import sys
import threading
from datetime import datetime, timezone

try:
    from impacket import smbserver
except ImportError:
    sys.exit("impacket is required: pip install impacket")

LOG_FILE = os.environ.get("SMB_LOG_FILE", "/logs/smb.json")
os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

_lock = threading.Lock()

# Patterns matched against impacket's internal log messages.
# impacket logs connection and auth events through its own log() method.
_RE_CONNECT = re.compile(r"Incoming connection \(([^,]+),\s*(\d+)\)")
_RE_AUTH    = re.compile(r"AUTHENTICATE_MESSAGE \((.+?)\\([^,]+),")
# NTLMv2 hash line: USER::DOMAIN:ServerChallenge:NTProofStr:blob
_RE_HASH    = re.compile(r"^(\S+?)::(\S*):([0-9a-fA-F]+):([0-9a-fA-F]+):([0-9a-fA-F]+)$")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(event: dict) -> None:
    with _lock:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
            fh.flush()


class _HoneypotServer(smbserver.SimpleSMBServer):
    """Wraps impacket's SimpleSMBServer; intercepts log() to emit JSON events."""

    def __init__(self, port: int) -> None:
        super().__init__(listenAddress="0.0.0.0", listenPort=port)
        self._port = port
        # impacket's SimpleSMBServer.__init__ already adds IPC$ by default.
        # Calling addShare("IPC$", ...) again raises "Section already exists".

    def log(self, msg: str, level: int = logging.DEBUG) -> None:
        logging.log(level, "[smb:%d] %s", self._port, msg)
        msg = str(msg)

        m = _RE_CONNECT.search(msg)
        if m:
            _write({
                "timestamp": _ts(),
                "type":      "connection",
                "src_host":  m.group(1),
                "src_port":  int(m.group(2)),
                "dst_port":  self._port,
                "protocol":  "smb",
            })
            return

        m = _RE_AUTH.search(msg)
        if m:
            domain, user = m.group(1).strip(), m.group(2).strip()
            _write({
                "timestamp": _ts(),
                "type":      "credentials",
                "src_host":  None,
                "src_port":  None,
                "protocol":  "smb",
                "login":     f"{domain}\\{user}" if domain else user,
                "password":  None,
            })
            return

        # NTLMv2 hash: USER::DOMAIN:challenge:response:blob — log the full hash
        # so it can be cracked offline with hashcat/john.
        m = _RE_HASH.match(msg.strip())
        if m:
            user, domain = m.group(1), m.group(2)
            _write({
                "timestamp": _ts(),
                "type":      "credentials",
                "src_host":  None,
                "src_port":  None,
                "protocol":  "smb",
                "login":     f"{domain}\\{user}" if domain else user,
                "password":  msg.strip(),
            })


def _serve(port: int) -> None:
    try:
        _HoneypotServer(port).start()
    except Exception as exc:
        logging.error("SMB server on :%d failed: %s", port, exc)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    # Port 139 (NetBIOS over TCP) in a daemon thread
    t = threading.Thread(target=_serve, args=(139,), daemon=True, name="smb-139")
    t.start()

    logging.info("SMB honeypot listening on :139 and :445")
    _serve(445)  # blocks in main thread


if __name__ == "__main__":
    main()
