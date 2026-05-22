import subprocess
import sys
from pathlib import Path

DEVNULL = "NUL" if sys.platform == "win32" else "/dev/null"


def ssh_key(raw):
    return str(Path(raw.replace("~", str(Path.home()))))


def ssh_base_args(key, port, ip):
    return [
        "ssh", "-i", key, "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={DEVNULL}",
        f"root@{ip}",
    ]


def scp_args(key, port):
    return [
        "scp", "-r", "-P", str(port), "-i", key,
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={DEVNULL}",
    ]


def run_ssh(key, port, ip, cmd, check=True, capture=False):
    args = ssh_base_args(key, port, ip) + [cmd]
    if capture:
        r = subprocess.run(args, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return subprocess.run(args, check=check)
