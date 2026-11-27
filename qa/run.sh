#!/usr/bin/env bash
# Run every check. From the repository root:  bash qa/run.sh
#
# The browser suites drive a real build through Playwright, served under the
# same base path GitHub Pages serves it under -- a build served at the root
# hides every URL the app builds from window.location, so the base path is not
# optional. They intercept Supabase over the network and answer with fixtures,
# so nothing here touches the live project and no key is needed.
set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${QA_PORT:-9804}"
BASE="http://127.0.0.1:${PORT}/crm101"

if [ "${QA_SKIP_BUILD:-}" != "1" ]; then
  echo "--- building against a stub Supabase host"
  NEXT_PUBLIC_BASE_PATH=/crm101 \
  NEXT_PUBLIC_SUPABASE_URL=https://stub.supabase.co \
  NEXT_PUBLIC_SUPABASE_ANON_KEY=stubkey \
    npx next build >/dev/null || { echo "the build failed"; exit 1; }
fi

# The suites route **stub.supabase.co/**, so a build pointed at the real project
# gets no fixtures and every row-dependent check fails for the wrong reason.
if ! grep -rqs "stub.supabase.co" out/_next/static/chunks/; then
  echo "this build does not point at stub.supabase.co -- rebuild without QA_SKIP_BUILD"
  exit 1
fi

SERVE="$(mktemp -d)"
ln -s "$PWD/out" "$SERVE/crm101"
python3 -m http.server "$PORT" --directory "$SERVE" >/dev/null 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null; rm -rf "$SERVE"' EXIT
sleep 2

echo "--- every suite must be able to fail"
blind=""
for f in qa/*.py; do
  case "$f" in */fixtures.py) continue;; esac       # a data module, not a suite
  grep -q "sys.exit" "$f" || blind="$blind $(basename "$f")"
done
if [ -n "$blind" ]; then
  echo "these report problems but exit 0, so they can never fail anything:$blind"
  exit 1
fi

fail=0
# A suite that fails prints its summary line and every problem under it, not
# just whichever line happened to come last.
run_one() {
  local out
  out="$(QA_BASE="$BASE" python3 -I "$1" 2>&1)"
  local code=$?
  printf '%-18s %s\n' "$(basename "$1")" "$(printf '%s\n' "$out" | grep '^===' | tail -1)"
  if [ "$code" != 0 ]; then
    printf '%s\n' "$out" | grep -v '^===' | sed 's/^/                   /'
    fail=1
  fi
}

echo "--- checks that read the source, no browser"
for f in qa/schema.py qa/parts.py qa/contract.py qa/reshoot.py qa/rails.py; do
  run_one "$f"
done

echo "--- checks that drive the built site"
for f in qa/test.py qa/nav.py qa/dashboard.py qa/details.py qa/looks.py qa/launch.py \
         qa/studio.py qa/courier.py qa/track.py qa/outreach.py qa/contrast.py \
         qa/mobile.py qa/dictate.py qa/occasions.py qa/social.py qa/inbox.py; do
  run_one "$f"
done

[ "$fail" = 0 ] && echo "--- all clear" || echo "--- something failed above"
exit "$fail"
