# mods/

Claude Code mods that ship with open-bridge. A mod is a Claude Code plugin with
function hooks (early access): it changes Claude Code's own interface or
behaviour, for example a card in the conversation, a line above the prompt or a
slash command. Mods run only in Claude Code; other agents cannot load them, and
nothing else in the Bridge depends on one.

| Mod | What it does | Guide |
|---|---|---|
| [`cockpit-relay`](cockpit-relay/) | lets the cockpit hand a question to the Claude Code session that steers the others, in any terminal | [`docs/bridge-cockpit.md`](../docs/bridge-cockpit.md) |

## Layout

```
mods/
  .claude-plugin/marketplace.json   the folder marketplace "open-bridge-mods"
  <mod>/.claude-plugin/plugin.json  one manifest per mod
  <mod>/hooks/                      hooks.json and the hooks module (TypeScript)
  <mod>/types/                      the mod's own type contract
  <mod>/tests/                      its tests
```

**Tier.** `mods/` is CORE, and the shipped set is enumerated in
`scripts/categorize-commits.py`: a new folder here routes as USER until it is
added there on purpose, so a mod nobody meant to publish never reaches a public
clone by default. A mod you keep for yourself lives in `.claude/mods/` (your
own folder marketplace beside this one), which is always USER.

## Install

From the Bridge folder, for this Bridge only:

```bash
claude plugin marketplace add ./mods --scope local
claude plugin install cockpit-relay@open-bridge-mods --scope local
```

Claude Code reads an installed mod straight from its folder here
(`claude plugin list` shows "Read from"). After a pull or an edit, start a new
session or run `/reload-plugins`. If `claude plugin list` shows no "Read from"
line, your Claude Code keeps a copy: run
`claude plugin update cockpit-relay@open-bridge-mods --scope local` first.

Each mod stays inert until its own switch in `bridge-config.yaml` is on (for
`cockpit-relay`: `cockpit.enabled: true`, the relay on unless `cockpit.relay: false`).
The former `briefing-ui` mod (the briefing as a card in Claude Code) was retired on
2026-10-13: the cockpit (`docs/bridge-cockpit.md`) does its work, and its relay lives on
in `cockpit-relay`.

## Tests

Two suites per mod, run from the Bridge folder:

| Suite | Command | Where it runs |
|---|---|---|
| pure functions and text tables (node, no Claude Code) | `npx -y -p typescript@5.6.3 -c 'node mods/cockpit-relay/tests/pure.test.mjs'` | CI (`validate.yml`, job `script-suites`) and locally |
| engine tests: the mod loaded in a simulated Claude Code over a fake Bridge (`*.test.tsx`) | `claude plugin test mods/cockpit-relay` | locally only, they need the `claude` CLI |

The pure tests compile the hooks with the pinned TypeScript, replace the import
from `claude-code` with stand-ins and check the exported functions with
`node:test`. Without TypeScript on the PATH they stop with one line naming the
`npx` command above; `TS=<path to typescript.js>` points them at another copy.

The engine tests are not a CI gate because the runner has no Claude Code. Run
them before a pull request that touches a mod, together with
`claude plugin validate mods` and `claude plugin validate mods/cockpit-relay`.

## Words

A mod's own user-facing words (buttons, help, the prompts it sends) live in one
table per language inside the mod, side by side under identical keys, English
as default and fallback, chosen at run time from config. Code, comments and
structure stay English; tests that assert rendered output in a non-English
table may quote that table's values verbatim
([`rules/language-policy.md`](../rules/language-policy.md)).
