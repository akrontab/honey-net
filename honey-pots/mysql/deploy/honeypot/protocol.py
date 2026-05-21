import asyncio
import random
import struct

from config import SERVER_VERSION
from logger import log_event
from packets import make_packet, ok_packet
from query_handler import QueryHandler


class MySQLHoneypot(asyncio.Protocol):
    """asyncio Protocol that emulates MySQL 8.0 HandshakeV10 / mysql_native_password.

    Accepts every connection, logs all events, delegates query responses to QueryHandler.
    """

    def connection_made(self, transport):
        self.transport  = transport
        self.peer       = transport.get_extra_info("peername") or ("0.0.0.0", 0)
        self.buf        = b""
        self.authed     = False
        self.username   = None
        self.query_handler = QueryHandler()

        log_event("connect", self.peer)
        self.transport.write(make_packet(0, self._build_greeting()))

    def data_received(self, data):
        self.buf += data
        while len(self.buf) >= 4:
            pkt_len = struct.unpack("<I", self.buf[:3] + b'\x00')[0]
            if len(self.buf) < 4 + pkt_len:
                break
            seq     = self.buf[3]
            payload = self.buf[4:4 + pkt_len]
            self.buf = self.buf[4 + pkt_len:]
            if not self.authed:
                self._handle_auth(payload, seq)
            else:
                self._handle_command(payload, seq)

    def connection_lost(self, exc):
        log_event("disconnect", self.peer, username=self.username)

    # ── Handshake ─────────────────────────────────────────────────────────────

    def _build_greeting(self) -> bytes:
        salt    = bytes(random.randint(1, 127) for _ in range(20))
        conn_id = random.randint(1, 2 ** 24)
        return (
            b'\x0a' +
            SERVER_VERSION.encode() + b'\x00' +
            struct.pack("<I", conn_id) +
            salt[:8] + b'\x00' +           # auth-data-1 + filler
            struct.pack("<H", 0xA28F) +    # capability flags (lower)
            bytes([0x21]) +                # charset: utf8
            struct.pack("<H", 0x0002) +    # status: AUTO_COMMIT
            struct.pack("<H", 0x000A) +    # capability flags (upper)
            bytes([len(salt) + 1]) +       # auth_plugin_data_len
            b'\x00' * 10 +                # reserved
            salt[8:] + b'\x00' +           # auth-data-2
            b'mysql_native_password\x00'
        )

    def _handle_auth(self, payload: bytes, seq: int):
        try:
            caps   = struct.unpack("<I", payload[0:4])[0]
            offset = 32  # caps(4) + max_packet(4) + charset(1) + reserved(23)

            end            = payload.index(b'\x00', offset)
            self.username  = payload[offset:end].decode("utf-8", errors="replace")
            offset         = end + 1

            CLIENT_SECURE_CONNECTION = 0x8000
            if caps & CLIENT_SECURE_CONNECTION:
                auth_len = payload[offset]
                offset  += 1 + auth_len
            else:
                end    = payload.find(b'\x00', offset)
                offset = (end + 1) if end != -1 else len(payload)

            database = ""
            CLIENT_CONNECT_WITH_DB = 0x0008
            if (caps & CLIENT_CONNECT_WITH_DB) and offset < len(payload):
                db_end   = payload.find(b'\x00', offset)
                db_end   = db_end if db_end != -1 else len(payload)
                database = payload[offset:db_end].decode("utf-8", errors="replace")

            self.query_handler.set_db(database)
            log_event("login", self.peer, username=self.username, database=database)
            self.authed = True
            self.transport.write(ok_packet(seq + 1))

        except Exception as exc:
            log_event("parse_error", self.peer, error=str(exc))
            self.transport.close()

    # ── Command dispatch ──────────────────────────────────────────────────────

    def _handle_command(self, payload: bytes, seq: int):
        if not payload:
            return
        cmd      = payload[0]
        arg      = payload[1:].decode("utf-8", errors="replace") if len(payload) > 1 else ""
        resp_seq = seq + 1

        if cmd == 0x01:    # COM_QUIT
            log_event("quit", self.peer, username=self.username)
            self.transport.close()

        elif cmd == 0x02:  # COM_INIT_DB
            self.query_handler.set_db(arg)
            log_event("use_db", self.peer, username=self.username, database=arg)
            self.transport.write(ok_packet(resp_seq))

        elif cmd == 0x03:  # COM_QUERY
            log_event("query", self.peer, username=self.username, query=arg)
            self.transport.write(self.query_handler.handle(arg, resp_seq))

        elif cmd == 0x04:  # COM_FIELD_LIST
            self.transport.write(make_packet(resp_seq, b'\xfe\x00\x00\x02\x00'))

        elif cmd == 0x0e:  # COM_PING
            self.transport.write(ok_packet(resp_seq))

        elif cmd == 0x1b:  # COM_CHANGE_USER
            new_user      = arg.split('\x00')[0] if arg else ""
            self.username = new_user
            log_event("change_user", self.peer, username=new_user)
            self.transport.write(ok_packet(resp_seq))

        else:
            log_event("command", self.peer, username=self.username, cmd=cmd, arg=arg[:200])
            self.transport.write(ok_packet(resp_seq))
