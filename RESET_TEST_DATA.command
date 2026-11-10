#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "Reset Commerce Business OS Team Test data"
echo "Close the CRM before continuing. Existing test data will be archived under data/backups."
printf "Type RESET to continue: "
read answer
[ "$answer" = "RESET" ] || { echo "Cancelled."; exit 0; }
stamp=$(date +%Y%m%d_%H%M%S)
mkdir -p data/backups
if [ -f data/commerce_crm.sqlite ]; then mv data/commerce_crm.sqlite "data/backups/reset_${stamp}.sqlite"; fi
# Full-backup restore evidence belongs to the workspace that was just reset.
# Archive those artifacts out of the active backup set so the new fictional
# workspace correctly starts at First backup required rather than inheriting
# a stale CREATED_NOT_VERIFIED state.
history="data/backups/reset_history_${stamp}"
mkdir -p "$history"
for pattern in team_full_*.zip v50_full_*.zip v9_full_*.zip; do
  for artifact in data/backups/$pattern; do
    [ -f "$artifact" ] && mv "$artifact" "$history/"
  done
done
rmdir "$history" 2>/dev/null || true
rm -rf data/static
cp -R data/sample_static data/static
cp data/sample_test_database.sqlite data/commerce_crm.sqlite
chmod 600 data/commerce_crm.sqlite 2>/dev/null || true
CRM_SKIP_TEAM_RUNTIME=1 python3 - <<'PY'
import sys
sys.path.insert(0,'app')
import team_start, team_beta6
team_start.configure_environment()
team_beta6.upgrade_workspace(team_start.ACTIVE_DB)
team_start._rotate_fictional_test_passwords()
PY
echo "Beta.6 test workspace reset with Team Test Warehouse, canonical activity history and new local sign-in credentials."
echo "Start the CRM again with START_APP.command."
