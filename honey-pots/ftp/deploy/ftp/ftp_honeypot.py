#!/usr/bin/env python3
"""
FTP honeypot — fake financial/crypto filesystem, accepts all credentials,
captures uploaded files, logs all events as newline-delimited JSON.
"""

import hashlib
import json
import logging
import os
import shutil
import signal
import sys
import threading
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
except ImportError:
    sys.exit("pyftpdlib is required: pip install pyftpdlib")

LOG_FILE      = os.environ.get("FTP_LOG_FILE",    "/logs/ftp.json")
SAMPLES_DIR   = os.environ.get("FTP_SAMPLES_DIR", "/samples")
PASSIVE_PORTS = range(60000, 60011)
FAKE_ROOT     = "/tmp/ftp-root"


def _resolve_passive_host() -> str | None:
    """Return the public IP to advertise in PASV responses.

    Uses FTP_PASSIVE_HOST if set; otherwise auto-detects via public IP
    endpoints. Returns None if detection fails (passive mode disabled).
    """
    explicit = os.environ.get("FTP_PASSIVE_HOST", "").strip()
    if explicit:
        return explicit
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                ip = r.read().decode().strip()
            if ip:
                sys.stdout.write(f"FTP passive host resolved via {url}: {ip}\n")
                sys.stdout.flush()
                return ip
        except Exception as exc:
            sys.stdout.write(f"FTP passive host detection failed ({url}): {exc}\n")
            sys.stdout.flush()
    sys.stdout.write("FTP passive host unresolvable — passive mode disabled\n")
    sys.stdout.flush()
    return None

os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

_lock = threading.Lock()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(event: dict) -> None:
    with _lock:
        with open(LOG_FILE, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(event) + "\n")
            fh.flush()


# ── Fake filesystem content ──────────────────────────────────────────────────

_README = """\
Financial Data Archive — Q1 2026
=================================
Trading accounts, wallet backups, and exchange API credentials.
Last backup : 2026-03-31
Created by  : backup_financial.py v2.1
"""

_PORTFOLIO = """\
ticker,type,quantity,avg_cost_usd,current_price_usd,unrealized_gain_usd
BTC,crypto,2.45712,38400.00,67823.41,73226.44
ETH,crypto,18.300,2100.00,3214.87,20732.12
SOL,crypto,142.0,95.50,171.23,10752.66
BNB,crypto,24.5,310.00,608.44,7313.78
USDC,crypto,8420.00,1.00,1.00,0.00
AAPL,stock,150,142.00,189.30,7095.00
MSFT,stock,75,298.00,415.80,8835.00
NVDA,stock,45,420.00,878.50,20632.50
"""

_TRANSACTIONS = """\
date,type,asset,quantity,price_usd,total_usd,exchange,note
2026-01-08,buy,BTC,0.25000,92100.00,23025.00,Coinbase,DCA purchase
2026-01-15,sell,ETH,2.000,3850.00,7700.00,Binance,rebalance
2026-01-22,buy,SOL,50.0,168.40,8420.00,Kraken,accumulate
2026-02-03,buy,BTC,0.10000,88500.00,8850.00,Coinbase,DCA purchase
2026-02-14,sell,BNB,5.0,615.00,3075.00,Binance,take profit
2026-02-27,buy,ETH,3.000,3120.00,9360.00,Coinbase,dip buy
2026-03-10,buy,BTC,0.07712,95200.00,7342.18,Coinbase,DCA purchase
2026-03-18,sell,SOL,30.0,182.00,5460.00,Kraken,partial exit
2026-03-28,buy,USDC,8420.00,1.00,8420.00,Coinbase,stablecoin reserve
"""

_BALANCE = """\
Account Summary — 2026-Q1
==========================
Crypto holdings  : $289,450.54
Equity holdings  :  $56,462.50
Cash / stables   :   $8,420.00
                   -----------
Total portfolio  : $354,333.04

YTD return       : +41.2%
Benchmark (BTC)  : +38.7%
"""

_ETH_KEYSTORE = json.dumps({
    "version": 3,
    "id": "3198bc9c-6672-5ab3-d995-4942343ae5b6",
    "address": "008aeeda4d805471df9b2a5b0f38a88253d3df5",
    "crypto": {
        "ciphertext": "517ead924a9d0dc3124507e3393d175ce3ff7c1e596521052e7d3cf3f47ee65e",
        "cipherparams": {"iv": "aac1efebe0519a429d124c92e0a15c3a"},
        "cipher": "aes-128-ctr",
        "kdf": "scrypt",
        "kdfparams": {
            "dklen": 32,
            "salt": "ae3cd4e7013836a3df6bd7241b12db061dbe2c6785853cce422d76a28f49fe34",
            "n": 8192,
            "r": 8,
            "p": 1,
        },
        "mac": "2103ac29920434fe7b4289b45bbb04af29c12f5daedd8c0edd868440c2f90b1",
    },
}, indent=2)

_SEEDS = """\
=== WALLET SEED PHRASE BACKUP — KEEP OFFLINE ===

BTC Main Wallet  (2.31 BTC | m/44'/0'/0')
abandon whisper jungle timber galaxy frozen chimney brisk harvest anchor surround marble

ETH / ERC-20  (18.3 ETH + 8420 USDC | m/44'/60'/0')
legal nominee patient trumpet venture dolphin robust walnut gravity pioneer ribbon chapter

SOL Cold Storage  (142 SOL | m/44'/501'/0'/0')
maple oxygen canoe fiction kingdom exhibit scatter thunder welcome canvas pepper segment

=== LAST VERIFIED: 2026-02-14 ===
"""

_BINANCE_KEYS = """\
Binance API Credentials
=======================
Label      : trading-bot-v2
API Key    : vmPUZE6mv9SD5VNHk4HlbGnOEs68unIKk1GfmzUBGLSLsN2oTTnRtMNQe3O1bOeB
Secret Key : NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM8A7qZpIqVAK
Permissions: READ, SPOT_TRADING, MARGIN
IP Lock    : None
Created    : 2025-11-03
"""

_COINBASE_CSV = """\
Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,Spot Price at Transaction,Subtotal,Total (inclusive of fees),Fees,Notes
2026-03-28,Buy,USDC,8420.00,USD,1.00,8420.00,8420.00,0.00,
2026-03-10,Buy,BTC,0.07712,USD,95200.00,7342.18,7381.07,38.89,
2026-02-27,Buy,ETH,3.000,USD,3120.00,9360.00,9406.80,46.80,
2026-02-03,Buy,BTC,0.10000,USD,88500.00,8850.00,8894.25,44.25,
2026-01-08,Buy,BTC,0.25000,USD,92100.00,23025.00,23140.13,115.13,
"""

_GAINS = """\
asset,acquired_date,disposed_date,proceeds_usd,cost_basis_usd,gain_loss_usd,term
ETH,2023-04-10,2026-01-15,7700.00,4200.00,3500.00,long
BNB,2024-09-22,2026-02-14,3075.00,1550.00,1525.00,long
SOL,2025-07-14,2026-03-18,5460.00,4926.00,534.00,short
"""

_FAKE_FILES: dict[str, str] = {
    "README.txt":                         _README,
    "accounts/portfolio_2026.csv":        _PORTFOLIO,
    "accounts/transactions_Q1_2026.csv":  _TRANSACTIONS,
    "accounts/balance_sheet.txt":         _BALANCE,
    "wallets/ethereum_keystore.json":     _ETH_KEYSTORE,
    "wallets/seed_phrases_backup.txt":    _SEEDS,
    "exchange/binance_api_keys.txt":      _BINANCE_KEYS,
    "exchange/coinbase_export.csv":       _COINBASE_CSV,
    "tax/crypto_gains_2025.csv":          _GAINS,
}


def _build_fake_fs() -> None:
    os.makedirs(FAKE_ROOT, exist_ok=True)
    for rel_path, content in _FAKE_FILES.items():
        full = os.path.join(FAKE_ROOT, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)


# ── Authorizer ───────────────────────────────────────────────────────────────

class HoneypotAuthorizer:
    """Accepts every credential; read + upload, no delete/rename."""

    def validate_authentication(self, username, password, handler):
        _write({
            "timestamp":  _ts(),
            "type":       "credentials",
            "src_host":   handler.remote_ip,
            "src_port":   handler.remote_port,
            "protocol":   "ftp",
            "session_id": handler._session_id,
            "login":      username,
            "password":   password,
        })

    def has_user(self, username: str) -> bool:
        return True

    def has_perm(self, username: str, perm: str, path=None) -> bool:
        return perm in "elrwm"  # list, retrieve, store, mkdir — no delete/rename

    def get_perms(self, username: str) -> str:
        return "elrwm"

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


# ── Handler ──────────────────────────────────────────────────────────────────

class HoneypotFTPHandler(FTPHandler):
    _session_id: str = ""

    def on_connect(self) -> None:
        self._session_id = uuid.uuid4().hex[:12]
        _write({
            "timestamp":  _ts(),
            "type":       "connection",
            "src_host":   self.remote_ip,
            "src_port":   self.remote_port,
            "dst_port":   21,
            "protocol":   "ftp",
            "session_id": self._session_id,
        })

    def on_disconnect(self) -> None:
        _write({
            "timestamp":  _ts(),
            "type":       "session_end",
            "src_host":   self.remote_ip,
            "src_port":   self.remote_port,
            "protocol":   "ftp",
            "session_id": self._session_id,
            "username":   getattr(self, "username", None),
        })

    def on_file_received(self, file: str) -> None:
        """Called after a successful STOR — copy to samples inbox with sidecar."""
        ts    = _ts()
        fname = os.path.basename(file)
        data  = Path(file).read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()

        os.makedirs(SAMPLES_DIR, exist_ok=True)
        shutil.copy2(file, os.path.join(SAMPLES_DIR, sha256))
        with open(os.path.join(SAMPLES_DIR, f"{sha256}.capture.json"),
                  "w", encoding="utf-8", newline="\n") as fh:
            json.dump({
                "src_ip":            self.remote_ip,
                "url":               None,
                "session_id":        self._session_id,
                "captured_at":       ts,
                "protocol":          "ftp",
                "original_filename": fname,
            }, fh)

        _write({
            "timestamp":  ts,
            "type":       "file_upload",
            "src_host":   self.remote_ip,
            "src_port":   self.remote_port,
            "protocol":   "ftp",
            "session_id": self._session_id,
            "username":   getattr(self, "username", None),
            "filename":   fname,
            "size":       len(data),
            "sha256":     sha256,
        })

    def on_file_sent(self, file: str) -> None:
        """Called after a successful RETR — attacker exfiltrated a fake file."""
        _write({
            "timestamp":  _ts(),
            "type":       "file_sent",
            "src_host":   self.remote_ip,
            "src_port":   self.remote_port,
            "protocol":   "ftp",
            "session_id": self._session_id,
            "username":   getattr(self, "username", None),
            "filename":   os.path.basename(file),
        })


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout)

    _build_fake_fs()

    HoneypotFTPHandler.authorizer = HoneypotAuthorizer()
    HoneypotFTPHandler.banner     = "220 FTP server ready."

    passive_host = _resolve_passive_host()
    if passive_host:
        HoneypotFTPHandler.masquerade_address = passive_host
        HoneypotFTPHandler.passive_ports      = PASSIVE_PORTS
    else:
        HoneypotFTPHandler.passive_ports = None

    server = FTPServer(("0.0.0.0", 21), HoneypotFTPHandler)
    server.max_cons        = 256
    server.max_cons_per_ip = 10

    signal.signal(signal.SIGTERM, lambda *_: (server.close_all(), sys.exit(0)))

    sys.stdout.write("FTP honeypot listening on :21\n")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
