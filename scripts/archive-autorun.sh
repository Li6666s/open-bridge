#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# archive-autorun.sh — schedule the mechanical archive, report it, notify on change.
#
# The third currency job, beside upstream-autoupdate.sh (CORE) and
# overlay-autosync.sh (ORG). This one keeps the WORK LOG from silting up: on the
# instance it comes from the log reached twelve unarchived periods, and every
# briefing re-read all of it, because archiving was a thing somebody had to
# remember. The reminder fired in week 28 and nothing acted on it for eleven weeks.
#
# It runs DAILY and exits quiet on the days nothing has closed, which is most of
# them. That is deliberately simpler than teaching a scheduler about ISO weeks, and
# it self-corrects after a machine was off — the same not-due shape the overlay job
# uses.
#
# The work itself is scripts/archive-autorun.py, which does only what is provably
# mechanical and records the judgement half as owed. Nothing here runs a model.
#
# Env (optional): SIGNAL_ACCOUNT + SIGNAL_RECIPIENT (both set → Signal push).
set -uo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" || exit 1

REPORT="work/archive-status.md"
LOG="${TMPDIR:-/tmp}/ob-archive-autorun.log"
LAST_SENT=".bridge/archive-autorun.notified"

notify() {
  { [ -n "${SIGNAL_ACCOUNT:-}" ] && [ -n "${SIGNAL_RECIPIENT:-}" ] \
    && command -v signal-cli >/dev/null 2>&1 \
    && signal-cli -a "$SIGNAL_ACCOUNT" send -m "$1" "$SIGNAL_RECIPIENT" >/dev/null 2>&1; } || true
}
notify_on_change() {   # quiet when the message has not changed since last time
  [ "$(cat "$LAST_SENT" 2>/dev/null)" = "$1" ] && return 0
  notify "$1"; mkdir -p .bridge; printf '%s' "$1" > "$LAST_SENT"
}
report() { mkdir -p work; { echo "# Log Archive, $(date '+%F %T')"; echo; printf '%s\n' "$@"; } > "$REPORT"; }

# One shared interpreter resolver, not a copy per script. It sets $PY.
. "$(dirname "$0")/lib/bridge-python.sh" || true
if [ -z "${PY:-}" ]; then
  report "- 🔴 no python3 with PyYAML found; the archive cannot run" \
         "- a scheduled run gets a minimal PATH; set \`BRIDGE_PYTHON\` (a plain path or file:// locator)"
  notify_on_change "🔴 log archive cannot run: no python3 with PyYAML"
  echo "archive-autorun: no usable python3"; exit 1
fi

LC_ALL=C "$PY" scripts/archive-autorun.py >"$LOG" 2>&1
rc=$?
out=$(cat "$LOG" 2>/dev/null)

case "$rc" in
  0)
    if printf '%s' "$out" | grep -q 'nothing closed'; then
      report "- ✓ nothing closed to archive" "" '```' "$out" '```'
      echo "archive-autorun: nothing closed"; exit 0
    fi
    n=$(printf '%s' "$out" | sed -n 's/.*archived \([0-9]\{1,\}\) period(s).*/\1/p' | head -1)
    report "- ✅ archived ${n:-?} period(s)" \
           "- narrative summaries and Phase 5 distillation are OWED — run \`/archive\` over work/archive" \
           "" '```' "$out" '```'
    notify_on_change "✅ log archive: ${n:-?} period(s) archived. Narrative + distillation owed (run /archive)."
    echo "archive-autorun: archived ${n:-?} period(s)"; exit 0 ;;
  3)
    # A refusal is a decision the job declines to make, not a failure of the job.
    report "- ⚠ refused, nothing written" "" '```' "$out" '```'
    notify_on_change "⚠ log archive refused: $(printf '%s' "$out" | head -1)"
    echo "archive-autorun: refused"; exit 0 ;;
  *)
    report "- 🔴 archive FAILED (exit $rc), nothing was left half-applied" \
           "- every archive file is written and verified before log.md is touched" \
           "" '```' "$out" '```'
    notify_on_change "🔴 log archive FAILED (exit $rc). See $LOG"
    echo "archive-autorun: failed (exit $rc)"; exit 1 ;;
esac
