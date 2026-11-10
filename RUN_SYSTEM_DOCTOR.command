#!/bin/bash
cd "$(dirname "$0")"
python3 app/team_start.py --doctor
echo
read -r -p "Press Return to close..." _
