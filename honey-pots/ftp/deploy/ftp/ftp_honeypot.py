#!/usr/bin/env python3
"""
FTP honeypot — accepts all credentials, logs connection and authentication
events as newline-delimited JSON.

Accepts every username/password combination so attackers believe they logged
in; this reveals more of their intent (directory listing, file downloads).
The served filesystem is an empty read-only directory inside the container.
"""

import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone

try:
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
except ImportError:
    sys.exit("pyftpdlib is required: pip install pyftpdlib")

LOG_FILE = os.environ.get("FTP_LOG_FILE", "/logs/ftp.json")
FAKE_ROOT = "/tmp/ftp-root"
os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
os.makedirs(FAKE_ROOT, exist_ok=True)

_lock = threading.Lock()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(event: dict) -> None:
    with _lock:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
            fh.flush()


class HoneypotAuthorizer:
    """Accepts every credential; logs username and password in plaintext."""

    def validate_authentication(self, username, password, handler):
        _write({
            "timestamp": _ts(),
            "type":      "credentials",
            "src_host":  handler.remote_ip,
            "src_port":  handler.remote_port,
            "protocol":  "ftp",
            "login":     username,
            "password":  password,
        })
        # Never raise AuthenticationFailed — accept everything.

    def has_user(self, username: str) -> bool:
        return True

    def has_perm(self, username: str, perm: str, path=None) -> bool:
        return perm in "elr"  # list, retrieve — no write perms

    def get_perms(self, username: str) -> str:
        return "elr"

    def get_home_dir(self, username: str) -> str:
        return FAKE_ROOT

    def get_msg_login(self, username: str) -> str:
        return "Login successful."

    def get_msg_quit(self, username: str) -> str:
        return "Goodbye."

    def impersonate_user(self, username: str, password: str) -> None:
        pass

    def terminate_impersonation(self, username: str) -> None:
        pass


class HoneypotFTPHandler(FTPHandler):
    def on_connect(self) -> None:
        _write({
            "timestamp": _ts(),
            "type":      "connection",
            "src_host":  self.remote_ip,
            "src_port":  self.remote_port,
            "dst_port":  21,
            "protocol":  "ftp",
        })


def main() -> None:
    # Suppress pyftpdlib's own verbose logging — we write our own events.
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout)

    HoneypotFTPHandler.authorizer = HoneypotAuthorizer()
    HoneypotFTPHandler.banner = "220 FTP server ready."
    # Passive mode disabled — only port 21 is exposed.
    HoneypotFTPHandler.passive_ports = None

    server = FTPServer(("0.0.0.0", 21), HoneypotFTPHandler)
    server.max_cons = 256
    server.max_cons_per_ip = 10

    signal.signal(signal.SIGTERM, lambda *_: (server.close_all(), sys.exit(0)))

    sys.stdout.write("FTP honeypot listening on :21\n")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
