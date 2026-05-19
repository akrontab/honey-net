#!/usr/bin/env python3
"""
MySQL honeypot — emulates MySQL 8.0 wire protocol to capture credentials and queries.

Listens on port 3306. Accepts every connection, logs every event to JSON.
Auth is always accepted (returns OK) so attackers stay connected long enough
to reveal their query patterns and tool signatures.

Captured events: connect, login, query, use_db, command, quit, disconnect.
"""

import asyncio
import json
import os
import random
import struct
from datetime import datetime, timezone

LOG_FILE = os.environ.get("LOG_FILE", "/logs/mysql-honeypot.json")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "3306"))
SERVER_VERSION = "8.0.35"
HONEYPOT_HOSTNAME = os.environ.get("HONEYPOT_HOSTNAME", "mysql-honeypot")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def log_event(event_type, peer, **kwargs):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "src_ip": peer[0],
        "src_port": peer[1],
        "server": HONEYPOT_HOSTNAME,
        **kwargs,
    }
    line = json.dumps(entry)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


# ── MySQL packet helpers ──────────────────────────────────────────────────────

def make_packet(seq, payload):
    return struct.pack("<I", len(payload))[:3] + bytes([seq & 0xFF]) + payload


def lenenc(s):
    """Length-encoded string for MySQL result set row data."""
    if s is None:
        return b'\xfb'
    if isinstance(s, str):
        s = s.encode("utf-8", errors="replace")
    n = len(s)
    if n < 251:
        return bytes([n]) + s
    if n < 65536:
        return b'\xfc' + struct.pack("<H", n) + s
    if n < 16777216:
        return b'\xfd' + struct.pack("<I", n)[:3] + s
    return b'\xfe' + struct.pack("<Q", n) + s


def col_def_packet(seq, name):
    """MySQL column definition packet (Protocol::ColumnDefinition41)."""
    payload = (
        lenenc("def") +           # catalog
        lenenc("") +              # schema
        lenenc("") +              # table alias
        lenenc("") +              # table
        lenenc(name) +            # name alias
        lenenc(name) +            # org_name
        b'\x0c' +                 # fixed-length fields (always 12)
        struct.pack("<H", 0x21) + # charset: utf8_general_ci
        struct.pack("<I", 0xFF) + # column display length
        b'\xfd' +                 # type: VAR_STRING
        struct.pack("<H", 0x00) + # flags
        b'\x00' +                 # decimals
        b'\x00\x00'               # filler
    )
    return make_packet(seq, payload)


def result_set(seq, columns, rows):
    """Build a complete MySQL text result set response."""
    pkts = [make_packet(seq, bytes([len(columns)]))]
    seq += 1
    for col in columns:
        pkts.append(col_def_packet(seq, col))
        seq += 1
    pkts.append(make_packet(seq, b'\xfe\x00\x00\x02\x00'))  # EOF
    seq += 1
    for row in rows:
        pkts.append(make_packet(seq, b''.join(lenenc(v) for v in row)))
        seq += 1
    pkts.append(make_packet(seq, b'\xfe\x00\x00\x02\x00'))  # EOF
    return b''.join(pkts)


def ok_packet(seq):
    # OK marker, affected=0, insert_id=0, status=AUTO_COMMIT, warnings=0
    return make_packet(seq, b'\x00\x00\x00\x02\x00\x00\x00')


# ── Protocol handler ──────────────────────────────────────────────────────────

class MySQLHoneypot(asyncio.Protocol):

    def connection_made(self, transport):
        self.transport = transport
        self.peer = transport.get_extra_info("peername") or ("0.0.0.0", 0)
        self.buf = b""
        self.authed = False
        self.username = None

        log_event("connect", self.peer)

        # Build HandshakeV10 greeting
        salt = bytes(random.randint(1, 127) for _ in range(20))
        conn_id = random.randint(1, 2 ** 24)

        greeting = (
            b'\x0a' +
            SERVER_VERSION.encode() + b'\x00' +
            struct.pack("<I", conn_id) +
            salt[:8] + b'\x00' +          # auth-data-1 + filler
            struct.pack("<H", 0xA28F) +   # capability flags (lower)
            bytes([0x21]) +               # charset: utf8
            struct.pack("<H", 0x0002) +   # status: AUTO_COMMIT
            struct.pack("<H", 0x000A) +   # capability flags (upper)
            bytes([len(salt) + 1]) +      # auth_plugin_data_len
            b'\x00' * 10 +               # reserved
            salt[8:] + b'\x00' +          # auth-data-2
            b'mysql_native_password\x00'
        )
        transport.write(make_packet(0, greeting))

    def data_received(self, data):
        self.buf += data
        while len(self.buf) >= 4:
            pkt_len = struct.unpack("<I", self.buf[:3] + b'\x00')[0]
            if len(self.buf) < 4 + pkt_len:
                break
            seq = self.buf[3]
            payload = self.buf[4:4 + pkt_len]
            self.buf = self.buf[4 + pkt_len:]
            if not self.authed:
                self._handle_auth(payload, seq)
            else:
                self._handle_command(payload, seq)

    def _handle_auth(self, payload, seq):
        try:
            caps = struct.unpack("<I", payload[0:4])[0]
            offset = 32  # caps(4) + max_packet(4) + charset(1) + reserved(23)

            end = payload.index(b'\x00', offset)
            self.username = payload[offset:end].decode("utf-8", errors="replace")
            offset = end + 1

            CLIENT_SECURE_CONNECTION = 0x8000
            if caps & CLIENT_SECURE_CONNECTION:
                auth_len = payload[offset]
                offset += 1 + auth_len
            else:
                end = payload.find(b'\x00', offset)
                offset = (end + 1) if end != -1 else len(payload)

            database = ""
            CLIENT_CONNECT_WITH_DB = 0x0008
            if (caps & CLIENT_CONNECT_WITH_DB) and offset < len(payload):
                db_end = payload.find(b'\x00', offset)
                db_end = db_end if db_end != -1 else len(payload)
                database = payload[offset:db_end].decode("utf-8", errors="replace")

            log_event("login", self.peer, username=self.username, database=database)
            self.authed = True
            self.transport.write(ok_packet(seq + 1))

        except Exception as exc:
            log_event("parse_error", self.peer, error=str(exc))
            self.transport.close()

    def _handle_command(self, payload, seq):
        if not payload:
            return
        cmd = payload[0]
        arg = payload[1:].decode("utf-8", errors="replace") if len(payload) > 1 else ""
        resp_seq = seq + 1

        if cmd == 0x01:    # COM_QUIT
            log_event("quit", self.peer, username=self.username)
            self.transport.close()
        elif cmd == 0x02:  # COM_INIT_DB
            log_event("use_db", self.peer, username=self.username, database=arg)
            self.transport.write(ok_packet(resp_seq))
        elif cmd == 0x03:  # COM_QUERY
            log_event("query", self.peer, username=self.username, query=arg)
            self._handle_query(arg, resp_seq)
        elif cmd == 0x04:  # COM_FIELD_LIST
            self.transport.write(make_packet(resp_seq, b'\xfe\x00\x00\x02\x00'))
        elif cmd == 0x0e:  # COM_PING
            self.transport.write(ok_packet(resp_seq))
        elif cmd == 0x1b:  # COM_CHANGE_USER
            new_user = arg.split('\x00')[0] if arg else ""
            log_event("change_user", self.peer, username=new_user)
            self.username = new_user
            self.transport.write(ok_packet(resp_seq))
        else:
            log_event("command", self.peer, username=self.username, cmd=cmd, arg=arg[:200])
            self.transport.write(ok_packet(resp_seq))

    def _handle_query(self, query, seq):
        q = query.strip().upper()

        if "@@VERSION_COMMENT" in q or "@@VERSION" in q:
            self.transport.write(result_set(seq, ["@@version_comment"], [["MySQL Community Server - GPL"]]))
        elif q in ("SELECT 1", "SELECT 1;"):
            self.transport.write(result_set(seq, ["1"], [["1"]]))
        elif "DATABASE()" in q:
            self.transport.write(result_set(seq, ["DATABASE()"], [[""]]))
        elif "USER()" in q or "CURRENT_USER()" in q:
            self.transport.write(result_set(seq, ["USER()"], [["root@localhost"]]))
        elif q.startswith("SHOW DATABASES"):
            self.transport.write(result_set(seq, ["Database"],
                [["information_schema"], ["mysql"], ["performance_schema"], ["sys"]]))
        elif q.startswith("SHOW TABLES"):
            self.transport.write(result_set(seq, ["Tables_in_mysql"], []))
        elif q.startswith("SHOW VARIABLES") or q.startswith("SHOW STATUS"):
            self.transport.write(result_set(seq, ["Variable_name", "Value"], []))
        elif q.startswith("SHOW PROCESSLIST"):
            self.transport.write(result_set(
                seq, ["Id", "User", "Host", "db", "Command", "Time", "State", "Info"], []))
        elif q.startswith(("SELECT", "DESC", "DESCRIBE", "EXPLAIN", "SHOW")):
            self.transport.write(result_set(seq, ["result"], []))
        else:
            self.transport.write(ok_packet(seq))

    def connection_lost(self, exc):
        log_event("disconnect", self.peer, username=self.username)


async def main():
    loop = asyncio.get_running_loop()
    server = await loop.create_server(MySQLHoneypot, "0.0.0.0", LISTEN_PORT, reuse_address=True)
    print(f"MySQL honeypot listening on 0.0.0.0:{LISTEN_PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
