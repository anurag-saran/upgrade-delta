#!/usr/bin/env bash
# Thin wrapper: live jackson demo cycle lives in the payments-service repo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${PAYMENTS_SERVICE_DIR:-$ROOT/../payments-service}"
SCRIPT="$APP/scripts/demo-live-cycle.sh"
[[ -x "$SCRIPT" || -f "$SCRIPT" ]] || {
  echo "FATAL: $SCRIPT not found. Clone/checkout payments-service next to upgrade-delta," >&2
  echo "       or set PAYMENTS_SERVICE_DIR." >&2
  exit 1
}
exec bash "$SCRIPT" "$@"
