---
name: cockpit
description: >-
  Open the Bridge cockpit, the local web page (127.0.0.1) that watches and steers the whole Bridge: briefing, work (inbox and tasks), agent tabs and sessions, workers, machines, tokens. Starts the server if needed. Trigger: "/cockpit", "cockpit", "open the cockpit", "dashboard", "Cockpit öffnen".
metadata:
  scope: core
---

# Cockpit

Opens the cockpit (`scripts/bridge-cockpit.py`, guide `docs/bridge-cockpit.md`).
It is an early version (alpha) and still being extended; mention that when a user meets it for the first time.

## Run

```bash
python3 scripts/bridge-cockpit.py open --json
```

It starts the server in the background (or reuses the running one) and opens the page itself: a
browser tab in the control workspace when the terminal driver can, else the default browser. Report
the answer's `url` in one line and nothing else. Arguments after `/cockpit` pass through:
`--via auto|cmux|system|none` picks where it opens, `status`, `url` and `stop` run that command
instead of `open`.

## When it refuses

| Exit | Meaning | Say |
|---|---|---|
| 2 | `cockpit.enabled` is not `true` (or the config is invalid) | how to switch it on: `cockpit: {enabled: true}` in `bridge-config.yaml` |
| 3 | the port is taken | which port (`cockpit.port`) and that another program holds it |
| 4 | the server did not come up | the last lines of `.bridge/cockpit/server.log` |
| 5 | the page could not be opened | the `url` to open by hand |
