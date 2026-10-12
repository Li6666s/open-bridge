# SPDX-License-Identifier: MIT
# bridge-python.sh — resolve an interpreter that can actually RUN this repo's
# Python, and set $PY to it. Source it; do not execute it.
#
#   . "$(dirname "$0")/lib/bridge-python.sh" || exit 1
#
# WHY THIS IS SHARED AND NOT COPIED. A scheduled run gets the service manager's
# minimal PATH (launchd: /usr/bin:/bin:/usr/sbin:/sbin), where /usr/bin/python3
# exists and has no PyYAML. A script that says `python3` therefore works by hand
# and silently fails on a schedule: the tool prints its error on stderr and
# nothing on stdout, and a caller reading stdout concludes there is no work.
# Measured on 2026-09-18, where a job reported "✓ no overlays subscribed" for six
# nights while 272 files sat subscribed and current.
#
# The fix is one definition, not a copy per script — the same argument board-pilot
# makes for its own fenced call site: three copies means a future fix lands in one
# of three, and the drifted copy is the one that runs unattended.
#
# The test is `import yaml`, never a path or a version: the only thing that matters
# is whether that interpreter can load the dependency every script here needs.
# BRIDGE_PYTHON may be a plain path or a `file://` locator, because a workload's
# `execution.env` refuses a bare path by schema and a locator is the only legal way
# to hand one in from a declaration.

_bp="${BRIDGE_PYTHON:-}"; _bp="${_bp#file://}"
PY=""
for _c in "$_bp" python3 "$HOME/.pyenv/shims/python3" /opt/homebrew/bin/python3 \
          /usr/local/bin/python3 /usr/bin/python3; do
  [ -n "$_c" ] || continue
  command -v "$_c" >/dev/null 2>&1 || continue
  "$_c" -c 'import yaml' >/dev/null 2>&1 || continue
  PY="$_c"; break
done
unset _bp _c
[ -n "$PY" ]   # the caller decides what a failure means; it must not be silent
