#!/usr/bin/env bash
# D4-4: generic issuer polling wrapper.
#
#   usage: cron_etf.sh <ASSET> <TICKER>
#
# Mirrors cron_ibit.sh exactly in structure (outer flock supplied by the
# crontab line, python-side inner flock inside the collector), but every
# IBIT-fixed name is derived from the ticker per D4-1:
#
#   log   = ledger/cron_<t>.log        with t = tolower(TICKER)
#
# cron_ibit.sh is left untouched; migrating IBIT onto this wrapper is a
# separate approval after stable observation.
#
# The collector module name stays scripts/collect_etf_ibit.py: the 33
# existing tests import it as `scripts.collect_etf_ibit`, and renaming it
# would require editing them, which the D4 scope forbids.
#
# No amounts on stdout.
set -u

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <ASSET> <TICKER>" >&2
  exit 2
fi

ASSET="$1"
TICKER="$2"

# Both values land in file paths and in a DB source_id, so keep them to a
# conservative charset instead of quoting our way around surprises.
case "$ASSET" in
  "" | *[!A-Za-z0-9]* ) echo "invalid asset: $ASSET" >&2; exit 2 ;;
esac
case "$TICKER" in
  "" | *[!A-Za-z0-9]* ) echo "invalid ticker: $TICKER" >&2; exit 2 ;;
esac

T="$(printf '%s' "$TICKER" | tr '[:upper:]' '[:lower:]')"

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE"
mkdir -p ledger

# Log size guard (>1MB keeps only the most recent 512KB) - same policy
# and thresholds as cron_ibit.sh.
LOG="ledger/cron_${T}.log"
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
  tail -c 524288 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

python3 scripts/collect_etf_ibit.py --asset "$ASSET" --ticker "$TICKER" >> "$LOG" 2>&1
