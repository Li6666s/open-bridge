# SPDX-License-Identifier: MIT
"""scripts/briefing.py act: a row's own step, through the section that offered it.

A command section's row may name `actions: [{id, label}]`; the section's `actions_argv` says how one
runs. `act` asks the section again and runs a step only when that row still offers it; an undo token
(`restore:...`) a step returned goes straight to the command, which checks it itself."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if "briefing" in sys.modules:
    bf = sys.modules["briefing"]
else:
    spec = importlib.util.spec_from_file_location("briefing", ROOT / "scripts" / "briefing.py")
    assert spec is not None and spec.loader is not None
    bf = importlib.util.module_from_spec(spec)
    sys.modules["briefing"] = bf
    spec.loader.exec_module(bf)

ROWS = [{"id": "2026-10/a", "title": "A", "actions": [{"id": "followed_up", "label": "followed_up"}]},
        {"id": "2026-10/b", "title": "B"}]


def bridge(tmp: Path, argv_extra=None) -> Path:
    (tmp / "workflow" / "briefings").mkdir(parents=True)
    (tmp / "rows.py").write_text(f"import json; print(json.dumps({ROWS!r}))\n", encoding="utf-8")
    (tmp / "step.py").write_text("import json, sys\nprint(json.dumps({'ok': True, 'did': sys.argv[2], 'id': sys.argv[1],"
                                 " 'undo': 'restore:sent._._'}))\n", encoding="utf-8")
    actions_argv = argv_extra or [sys.executable, "step.py", "{id}", "{action}"]
    (tmp / "workflow" / "briefings" / "p.yaml").write_text(json.dumps({
        "id": "p", "title": "P", "sections": [{"kind": "command", "id": "apps", "argv": [sys.executable, "rows.py"],
                                               "actions_argv": actions_argv}]}), encoding="utf-8")
    return tmp


def run(root, *args, capsys):
    code = bf.main(["--root", str(root), "act", "p", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_step_the_row_offers_runs_and_its_result_comes_back(tmp_path, capsys):
    root = bridge(tmp_path)
    code, out, _ = run(root, "apps", "2026-10/a", "followed_up", capsys=capsys)
    assert code == 0 and json.loads(out) == {"ok": True, "did": "followed_up", "id": "2026-10/a", "undo": "restore:sent._._"}


def test_a_step_the_row_does_not_offer_is_refused_before_anything_runs(tmp_path, capsys):
    root = bridge(tmp_path)
    for row, action in (("2026-10/a", "turned_down"), ("2026-10/b", "followed_up"), ("2026-10/zz", "followed_up"),
                        ("2026-10/a", "followed_up; rm"), ("2026-10/a", "restore:../x")):
        code, out, err = run(root, "apps", row, action, capsys=capsys)
        assert code == 2 and out == "" and err, (row, action)


def test_an_undo_token_goes_to_the_command_even_when_the_row_is_gone(tmp_path, capsys):
    root = bridge(tmp_path)
    code, out, _ = run(root, "apps", "2026-10/gone", "restore:sent.2026-09-25._", capsys=capsys)
    assert code == 0 and json.loads(out)["did"] == "restore:sent.2026-09-25._"


def test_actions_argv_is_checked_like_argv_and_needs_whole_placeholders():
    ok = {"kind": "command", "id": "x", "argv": ["a"], "actions_argv": ["python3", "s.py", "{id}", "{action}"]}
    assert not [p for p in bf._section_types(ok)]
    for bad in (["python3", "s.py", "x{id}", "{action}"], ["python3", "s.py", "{id}"], "python3 s.py", []):
        problems = bf._section_types({**ok, "actions_argv": bad})
        assert problems, bad
