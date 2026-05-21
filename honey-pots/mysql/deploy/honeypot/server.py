#!/usr/bin/env python3
"""
MySQL honeypot — entry point.

Listens on LISTEN_PORT (default 3306). Accepts every connection, logs every event to JSON.
Auth is always accepted so attackers stay connected long enough to reveal query patterns
and tool signatures.

Captured events: connect, login, query, use_db, command, quit, disconnect.
"""

import asyncio

from config import LISTEN_PORT
from protocol import MySQLHoneypot


async def main():
    loop   = asyncio.get_running_loop()
    server = await loop.create_server(MySQLHoneypot, "0.0.0.0", LISTEN_PORT, reuse_address=True)
    print(f"MySQL honeypot listening on 0.0.0.0:{LISTEN_PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
