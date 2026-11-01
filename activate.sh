#!/usr/bin/env bash
# Activates .venv in the current shell. Must be sourced, not executed:
#   source ./activate.sh

if [ -n "${BASH_VERSION:-}" ] && [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "Error: run this with: source ./activate.sh" >&2
    exit 1
fi

_honey_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Git Bash on Windows gets Scripts/; macOS and Linux get bin/.
if [ -f "$_honey_dir/.venv/bin/activate" ]; then
    . "$_honey_dir/.venv/bin/activate"
elif [ -f "$_honey_dir/.venv/Scripts/activate" ]; then
    . "$_honey_dir/.venv/Scripts/activate"
else
    echo "Error: .venv not found. Run ./setup.sh first." >&2
    unset _honey_dir
    return 1
fi

unset _honey_dir
