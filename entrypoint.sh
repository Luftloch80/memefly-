#!/bin/sh
# Mirrors main.py's own safety gate: the bot container only ever adds
# --live if BOTH env safety switches are set, exactly like running it
# outside Docker would require.
set -e

if [ "${LIVE_TRADING:-false}" = "true" ] && [ "${I_UNDERSTAND_THE_RISK:-no}" = "yes" ]; then
  echo "[entrypoint] LIVE_TRADING=true and I_UNDERSTAND_THE_RISK=yes -- starting in LIVE mode"
  exec python -m memefly.main --live
else
  echo "[entrypoint] starting in DRY RUN mode"
  exec python -m memefly.main
fi
