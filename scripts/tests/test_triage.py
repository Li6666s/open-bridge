# SPDX-License-Identifier: MIT
"""Contract for `triage.py`: every open task and inbox item gets what it is about, whether it can go,
and who does it; one cheap batch call per chunk, a cache per item, hard rules over the model.

No network: git, gh and the model command are a fake runner (the one of test_task_review)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts" / "tests"))
SPEC = importlib.util.spec_from_file_location("triage_under_test", ROOT / "scripts" / "triage.py")
triage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(triage)
from test_task_review import Fake, add, HAIKU, NOW  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "log.md").write_text(
        "## Wed 30.09\n\n| Timestamp | Glyph | Context | What |\n|---|---|---|---|\n"
        "| 2026-09-30 10:00 | 💻 | alpha | alpha: tests green, PR open |\n", encoding="utf-8")
    return tmp_path


def inbox_item(root, iid, summary, kind="question", gate="free", task=None):
    d = root / "work" / "inbox" / iid
    (d / "events").mkdir(parents=True)
    (d / "item.yaml").write_text(
        f"schema_version: 1\ncreated: '2026-10-08T09:00'\nfrom: test\nkind: {kind}\nsummary: '{summary}'\n"
        f"gate: {gate}\nurgency: later\n" + (f"task: {task}\n" if task else ""), encoding="utf-8")


def answers(rows):
    """The model answers rows for the keys the prompt names."""
    return lambda prompt: [r for r in rows if f"## {r['key']}\n" in prompt]


ROWS = [
    {"key": "task:alpha", "gist": "Importer fertigstellen", "verdict": "continue", "doer": "ai", "effort": "small",
     "why": "code in the repo, tests exist", "reason": "PR open"},
    {"key": "task:beta", "gist": "Send the invoice to the customer", "verdict": "continue", "doer": "ai", "effort": "small",
     "why": "only the sending", "reason": "the draft is ready"},
    {"key": "inbox:20261008-0900-frage-a1b2", "gist": "A question about the date", "verdict": "keep", "doer": "ai",
     "effort": "small", "why": "", "reason": "open"},
    {"key": "inbox:20261008-0901-fund-c3d4", "gist": "Log-Fund erledigt", "verdict": "close", "doer": "ai",
     "effort": "small", "why": "", "reason": "fixed on 09.10."},
]


def setup(repo):
    add(repo, "alpha")
    add(repo, "beta", body="- [ ] Send the invoice to the customer by mail\n", st="backlog")
    add(repo, "gamma", st="done")
    add(repo, "stream-x", kind="streams")
    inbox_item(repo, "20261008-0900-frage-a1b2", "A question about the date", kind="question", gate="only-you")
    inbox_item(repo, "20261008-0901-fund-c3d4", "Log-Fund", kind="finding", gate="free")


def test_every_open_task_and_inbox_item_gets_gist_verdict_and_doer(repo):
    setup(repo)
    fake = Fake(answers={HAIKU: answers(ROWS)})
    out = triage.triage(repo, run=fake, now=NOW)
    by = {x["key"]: x for x in out["items"]}
    # all statuses but done; streams never close and are not triaged; both inbox items
    assert set(by) == {"task:alpha", "task:beta", "inbox:20261008-0900-frage-a1b2", "inbox:20261008-0901-fund-c3d4"}
    assert by["task:alpha"]["gist"] == "Importer fertigstellen" and by["task:alpha"]["doer"] == "ai"
    assert by["task:alpha"]["effort"] == "small" and by["task:alpha"]["kind"] == "task"
    assert by["inbox:20261008-0901-fund-c3d4"]["verdict"] == "close"
    assert len(fake.model_calls()) == 1 and fake.model_calls()[0][0][fake.model_calls()[0][0].index("--model") + 1] == HAIKU
    assert out["cost_usd"] > 0 and out["counts"]["close"] == 1


def test_hard_rules_win_over_the_model(repo):
    setup(repo)
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW)
    by = {x["key"]: x for x in out["items"]}
    # a gate only-you, and a question to the person, is never the AI's
    assert by["inbox:20261008-0900-frage-a1b2"]["doer"] == "you"
    # sending mail is outbound: the agent may prepare it, the click is the person's
    assert by["task:beta"]["doer"] == "either" and "click" in by["task:beta"]["why"]
    # the prompt says so too
    prompt = Fake(answers={HAIKU: answers(ROWS)})
    triage.triage(repo, run=prompt, now=NOW, fresh=True)
    text = prompt.model_calls()[0][1]
    assert "merge" in text and "deploy" in text and "send" in text


def test_a_second_run_asks_no_model_and_a_change_asks_again(repo):
    setup(repo)
    triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW)
    again = Fake(answers={HAIKU: answers(ROWS)})
    out = triage.triage(repo, run=again, now=NOW)
    assert again.model_calls() == [] and all(x["cached"] for x in out["items"])
    inbox_item(repo, "20261008-0902-neu-e5f6", "Neue Idee", kind="idea")
    third = Fake(answers={HAIKU: answers(ROWS + [{"key": "inbox:20261008-0902-neu-e5f6", "gist": "Neue Idee",
                                                   "verdict": "keep", "doer": "either", "effort": "medium",
                                                   "why": "", "reason": ""}])})
    out = triage.triage(repo, run=third, now=NOW)
    (argv, prompt), = third.model_calls()
    assert "## inbox:20261008-0902-neu-e5f6\n" in prompt and "## task:alpha\n" not in prompt


def test_the_task_check_verdict_wins_for_a_task_it_judged(repo):
    setup(repo)
    (repo / ".bridge").mkdir()
    (repo / ".bridge" / "task-review.json").write_text(json.dumps({"tasks": {}, "last": {"tasks": [
        {"slug": "alpha", "verdict": "close", "reason": "PR gemergt", "kept": False}]}}))
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW)
    alpha = next(x for x in out["items"] if x["key"] == "task:alpha")
    assert (alpha["verdict"], alpha["reason"], alpha["verdict_from"]) == ("close", "PR gemergt", "check")


def test_a_model_answer_out_of_range_becomes_unclear_and_a_long_gist_is_cut(repo):
    setup(repo)
    rows = [dict(ROWS[0], verdict="maybe", doer="robot", effort="huge", gist="x" * 300)]
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(rows)}), now=NOW)
    alpha = next(x for x in out["items"] if x["key"] == "task:alpha")
    assert alpha["verdict"] == "unclear" and alpha["doer"] == "either" and alpha["effort"] is None
    assert len(alpha["gist"]) <= 90
    missing = next(x for x in out["items"] if x["key"] == "task:beta")   # no answer at all
    assert missing["verdict"] == "unclear" and missing["gist"]                # the title stands in


def test_the_reason_of_a_hard_rule_comes_in_the_bridges_language():
    item = {"kind": "task", "title": "Send the offer", "evidence": {}}
    got = {"doer": "ai", "effort": "small", "why": ""}
    assert set(triage.WHY["de"]) == set(triage.WHY["en"])
    german = triage._rules(item, got, triage.why_words({"language": {"conversation": "de"}}))
    english = triage._rules(item, got, triage.why_words({}))
    assert german["why"] == triage.WHY["de"]["outbound"] and english["why"] == triage.WHY["en"]["outbound"]
