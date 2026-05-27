import os

LOG_FILE         = os.environ.get("LOG_FILE",          "/logs/mysql.json")
LISTEN_PORT      = int(os.environ.get("LISTEN_PORT",   "3306"))
SERVER_VERSION   = "8.0.35"
HONEYPOT_HOSTNAME = os.environ.get("HONEYPOT_HOSTNAME", "mysql-honeypot")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
