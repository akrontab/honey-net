#!/usr/bin/env python3
"""
HTTP / web-app honeypot — a low-interaction decoy presenting a generic corporate
admin panel. Logs every request, captures credential POSTs and file uploads, and
ships newline-delimited JSON events.

Stdlib only (http.server) — no third-party dependencies, so the image builds in
seconds and the resident footprint stays small.

Behaviour:
  * Serves a fake "Acme Internal Portal" landing + /admin sign-in form.
  * Responds plausibly to common honeytoken probes (.env, .git/config,
    .aws/credentials, ...) to keep scanners engaged.
  * Emits one event per TCP connection (connect / session_end) and one per
    request. Credential POSTs become `login` events; uploaded request bodies are
    persisted and become `download` events (a sample was captured).

Captured uploads are written to SAMPLES_DIR as <sha256> plus a
<sha256>.capture.json provenance sidecar — the same contract Cowrie's
capture-writer uses, so the `metadata` addon canonicalises them and
`malware-sender` ships them to the catalog with no changes.

Env vars:
  HTTP_LOG_FILE   newline-delimited JSON event log (default /logs/http.json)
  SAMPLES_DIR     where uploads are dropped       (default /samples)
  LISTEN_PORT     TCP port to bind                (default 80)
  MAX_UPLOAD      max bytes persisted per upload  (default 3000000)
"""

import base64
import hashlib
import json
import os
import signal
import ssl
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOG_FILE    = os.environ.get("HTTP_LOG_FILE", "/logs/http.json")
SAMPLES_DIR = os.environ.get("SAMPLES_DIR", "/samples")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "80"))
TLS_PORT    = int(os.environ.get("LISTEN_TLS_PORT", "443"))
TLS_CERT    = os.environ.get("TLS_CERT", "")
TLS_KEY     = os.environ.get("TLS_KEY", "")
MAX_UPLOAD  = int(os.environ.get("MAX_UPLOAD", "3000000"))

os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

_lock = threading.Lock()

# Credential field names attacker tooling commonly submits.
_USER_FIELDS = ("username", "user", "login", "email", "uname", "usr")
_PASS_FIELDS = ("password", "pass", "passwd", "pwd", "pw")

# Endpoints that present (and capture against) a login form.
_LOGIN_PATHS = ("/login", "/admin", "/admin/login", "/wp-login.php", "/user/login")

# Honeytoken responses — plausible bait for common scanner probes. Keys lowercased.
_BAIT = {
    "/.env": (
        "APP_ENV=production\n"
        "APP_KEY=base64:Zk9SVEhFSE9ORVlQT1RPTkxZ===\n"
        "DB_CONNECTION=mysql\nDB_HOST=10.0.0.12\nDB_DATABASE=acme_portal\n"
        "DB_USERNAME=acme_app\nDB_PASSWORD=S3cr3t-Pa55!\n"
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
    ),
    "/.git/config": (
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        '[remote "origin"]\n\turl = https://github.com/acme-corp/portal.git\n'
    ),
    "/.aws/credentials": (
        "[default]\naws_access_key_id = AKIAIOSFODNN7EXAMPLE\n"
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
    ),
}

_LANDING = (
    "<!doctype html><html><head><title>Acme Internal Portal</title></head>"
    "<body style='font-family:sans-serif'><h2>Acme Internal Portal</h2>"
    "<p>Authorised personnel only. <a href='/admin'>Sign in</a></p></body></html>"
)

_LOGIN_FORM = (
    "<!doctype html><html><head><title>Sign in &middot; Acme Portal</title></head>"
    "<body style='font-family:sans-serif'><h2>Administrator sign in</h2>"
    "{msg}<form method='POST' action='{action}'>"
    "<p>Username <input name='username'></p>"
    "<p>Password <input name='password' type='password'></p>"
    "<button type='submit'>Sign in</button></form></body></html>"
)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(event: dict) -> None:
    line = json.dumps(event)
    with _lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
        except OSError:
            pass
    print(line, flush=True)


def _first(form: dict, fields) -> str | None:
    for key in fields:
        if key in form and form[key]:
            return form[key][0]
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "Apache/2.4.41"
    sys_version = "(Ubuntu)"
    protocol_version = "HTTP/1.1"

    # ── connection lifecycle (per TCP connection) ─────────────────────
    def setup(self):
        super().setup()
        self.session_id = uuid.uuid4().hex[:12]
        self._emit("connect")

    def finish(self):
        try:
            self._emit("session_end")
        finally:
            super().finish()

    def log_message(self, *args):  # silence stderr; we emit our own events
        pass

    def _src_ip(self) -> str:
        try:
            xff = self.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[0].strip()
            xri = self.headers.get("X-Real-IP", "")
            if xri:
                return xri.strip()
        except AttributeError:
            pass
        return self.client_address[0]

    def _emit(self, etype, **extra):
        _write({
            "timestamp":  _ts(),
            "type":       etype,
            "protocol":   "http",
            "src_host":   self._src_ip(),
            "src_port":   self.client_address[1],
            "session_id": self.session_id,
            **extra,
        })

    # ── verb dispatch ─────────────────────────────────────────────────
    def do_GET(self):     self._handle()
    def do_HEAD(self):    self._handle(head=True)
    def do_POST(self):    self._handle()
    def do_PUT(self):     self._handle()
    def do_DELETE(self):  self._handle()
    def do_OPTIONS(self): self._handle()
    def do_PATCH(self):   self._handle()

    # ── core ──────────────────────────────────────────────────────────
    def _handle(self, head=False):
        path = urlparse(self.path).path
        body = self._read_body()
        ua = self.headers.get("User-Agent")

        creds = self._extract_creds(body)
        if creds:
            self._emit("login", method=self.command, path=path,
                       username=creds[0], password=creds[1], auth_method=creds[2], user_agent=ua)
        elif body and self.command in ("POST", "PUT") and self._looks_like_upload(body):
            self._capture_upload(path, body, ua)
        else:
            self._emit("request", method=self.command, path=path,
                       payload=f"{self.command} {path}", user_agent=ua)

        self._respond(path, head=head)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return b""
        if length <= 0:
            return b""
        to_read = min(length, MAX_UPLOAD)
        try:
            body = self.rfile.read(to_read)
        except OSError:
            self.close_connection = True
            return b""
        if length > MAX_UPLOAD:
            # Can't safely keep-alive after a truncated read — close the stream.
            self.close_connection = True
        return body

    def _extract_creds(self, body: bytes):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8", "replace")
                if ":" in decoded:
                    user, pw = decoded.split(":", 1)
                    return (user, pw, "basic")
            except (ValueError, base64.binascii.Error):
                pass
        ctype = self.headers.get("Content-Type", "")
        if body and "application/x-www-form-urlencoded" in ctype:
            form = parse_qs(body.decode("utf-8", "replace"))
            user = _first(form, _USER_FIELDS)
            pw = _first(form, _PASS_FIELDS)
            if user is not None or pw is not None:
                return (user, pw, "form")
        return None

    def _looks_like_upload(self, body: bytes) -> bool:
        ctype = self.headers.get("Content-Type", "").lower()
        if "multipart/form-data" in ctype:
            return True
        if self.command == "PUT":
            return True
        if ctype.startswith(("application/octet-stream", "application/x-")):
            return True
        return body[:4] == b"\x7fELF" or body[:2] == b"MZ"

    def _extract_upload(self, body: bytes, ctype: str):
        """Return (filename, filebytes). Best-effort multipart extraction."""
        if "multipart/form-data" in ctype.lower() and "boundary=" in ctype:
            boundary = ctype.split("boundary=", 1)[1].strip().strip('"')
            delim = ("--" + boundary).encode()
            try:
                for part in body.split(delim):
                    header, sep, content = part.partition(b"\r\n\r\n")
                    if not sep or b"filename=" not in header:
                        continue
                    fname = None
                    for token in header.replace(b"\r\n", b";").split(b";"):
                        token = token.strip()
                        if token.startswith(b"filename="):
                            fname = token.split(b"=", 1)[1].strip().strip(b'"').decode(
                                "utf-8", "replace")
                    content = content.rsplit(b"\r\n", 1)[0]  # trim CRLF before next boundary
                    if content:
                        return (fname or "upload", content)
            except (ValueError, IndexError):
                pass
        return (None, body)

    def _capture_upload(self, path: str, body: bytes, ua):
        ctype = self.headers.get("Content-Type", "")
        filename, data = self._extract_upload(body, ctype)
        sha = hashlib.sha256(data).hexdigest()
        try:
            os.makedirs(SAMPLES_DIR, exist_ok=True)
            dest = os.path.join(SAMPLES_DIR, sha)
            if not os.path.exists(dest):
                with open(dest, "wb") as fh:
                    fh.write(data)
            # Provenance sidecar consumed by the metadata addon.
            with open(dest + ".capture.json", "w", encoding="utf-8") as fh:
                json.dump({
                    "src_ip":      self._src_ip(),
                    "url":         f"{self.headers.get('Host', '')}{path}",
                    "session_id":  self.session_id,
                    "captured_at": _ts(),
                }, fh)
        except OSError:
            pass
        self._emit("download", method=self.command, path=path,
                   payload=f"{self.command} {path}", filename=filename,
                   sample_sha256=sha, size=len(data), user_agent=ua)

    def _respond(self, path: str, head=False):
        p = path.lower()
        if p in _BAIT:
            status, ctype, text = 200, "text/plain; charset=utf-8", _BAIT[p]
        elif p in ("/", "/index.html", "/index.php"):
            status, ctype, text = 200, "text/html; charset=utf-8", _LANDING
        elif p in _LOGIN_PATHS:
            if self.command == "POST":
                status, ctype = 401, "text/html; charset=utf-8"
                text = _LOGIN_FORM.format(
                    action=path, msg="<p style='color:#b00'>Invalid username or password.</p>")
            else:
                status, ctype = 200, "text/html; charset=utf-8"
                text = _LOGIN_FORM.format(action=path, msg="")
        else:
            status, ctype = 404, "text/html; charset=utf-8"
            text = "<!doctype html><title>404 Not Found</title><h1>Not Found</h1>"

        data = text.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if not head:
                self.wfile.write(data)
        except OSError:
            self.close_connection = True


def _make_tls_server() -> ThreadingHTTPServer:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=TLS_CERT, keyfile=TLS_KEY)
    srv = ThreadingHTTPServer(("0.0.0.0", TLS_PORT), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv


def main() -> None:
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    httpd = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    tls_srv = None
    if TLS_CERT and TLS_KEY and os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY):
        try:
            tls_srv = _make_tls_server()
            threading.Thread(target=tls_srv.serve_forever, daemon=True).start()
            sys.stdout.write(f"HTTP honeypot listening on :{LISTEN_PORT} and :{TLS_PORT} (TLS)\n")
        except Exception as exc:
            sys.stdout.write(f"WARNING: TLS startup failed: {exc}\n")
            tls_srv = None
    else:
        sys.stdout.write(f"HTTP honeypot listening on :{LISTEN_PORT}\n")
    sys.stdout.flush()

    try:
        httpd.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        httpd.server_close()
        if tls_srv:
            tls_srv.server_close()


if __name__ == "__main__":
    main()
