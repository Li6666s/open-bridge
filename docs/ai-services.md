---
summary: "Configure which local AI CLI handles each Bridge service, keep Claude as the compatibility default, and run a selected provider from worker scripts."
type: reference
last_updated: 2026-10-12
related:
  - ../scripts/lib/ai_services.py
  - ../scripts/ai-run.py
  - bridge-cockpit.md
---

# AI service routing

Bridge services can select a local AI CLI independently. The shared adapter is
`scripts/lib/ai_services.py`; per-instance choices live in
`workflow/ai-services/<service>.yaml`. The config template and schema define the
supported fields. Claude remains the default when no service entry exists, so
existing Claude-backed flows continue to work.

The current service IDs are `briefing-chat`, `task-review`, and `triage`. The
briefing chat also lets a user choose Claude or Codex for a conversation. That
choice applies to the current and subsequent turns; switching providers carries
the completed conversation as prompt context and starts a fresh provider
session. A failed switch leaves the original conversation intact. Choosing
“Use service default” clears the per-chat override.

Worker scripts can use the same routing layer:

```sh
python3 scripts/ai-run.py --service triage --show
python3 scripts/ai-run.py --service triage --json "Classify this item"
```

Use `--provider codex` to override one invocation. The adapter does not silently
fall back to another provider. Codex chat runs in a read-only sandbox; the
worker wrapper also disables its shell tool. Reported cost is unknown when the
CLI does not provide a reliable amount.
