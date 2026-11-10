#!/bin/bash
cd "$(dirname "$0")"
python3 app/team_start.py --prepare-full-runtime
echo
read -r -p "Press Return to close..." _
