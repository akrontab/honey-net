#!/usr/bin/env bash
# Creates .venv and installs honey-net Python dependencies.

set -e

MIN_MAJOR=3; MIN_MINOR=10

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python $MIN_MAJOR.$MIN_MINOR+ and try again." >&2
    exit 1
fi

ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
major=${ver%%.*}; minor=${ver##*.}

if [ "$major" -lt "$MIN_MAJOR" ] || { [ "$major" -eq "$MIN_MAJOR" ] && [ "$minor" -lt "$MIN_MINOR" ]; }; then
    echo "Error: Python $MIN_MAJOR.$MIN_MINOR+ required — got $ver" >&2
    exit 1
fi

dir="$(cd "$(dirname "$0")" && pwd)"
venv="$dir/.venv"

if [ ! -d "$venv" ]; then
    echo "Creating .venv ..."
    python3 -m venv "$venv"
else
    echo ".venv already exists"
fi

echo "Installing dependencies ..."
"$venv/bin/pip" install -r "$dir/requirements.txt" --quiet

echo "
Done.

Activate the environment:
  source .venv/bin/activate

Then run any script:
  python deploy.py --help
  python connect.py --help
  python sync_ips.py
"
