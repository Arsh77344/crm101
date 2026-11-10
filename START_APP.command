#!/bin/bash
set -u
cd "$(dirname "$0")"
for launch_python in .venv/bin/python runtime/venv/bin/python python3.14 python3.13 python3.12 python3; do
  if "$launch_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)' >/dev/null 2>&1; then
    exec "$launch_python" app/team_start.py
  fi
done
echo "Python 3.12 or newer is required. Install Python from python.org, then try again."
read -r -p "Press Return to close..." _
exit 1
