# SPDX-License-Identifier: MIT
"""Provider selection is per consumer, never a global CLI replacement."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import ai_services as ai

SID = "11111111-2222-3333-4444-555555555555"


def config(root, service="briefing-chat", provider="codex", models=None):
    folder = root / "workflow" / "ai-services"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{service}.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, "scope": "user", "id": service,
                                    "provider": provider, "models": models or {}}))
    return path


def events(text="answer", *, sid=SID, completed=True):
    data = [{"type": "thread.started", "thread_id": sid},
            {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": text}}]
    if completed:
        data.append({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 1}})
    return "\n".join(json.dumps(x) for x in data)


def test_defaults_and_independent_consumers(tmp_path):
    assert ai.select(tmp_path, "task-review", "sonnet").model == ai.CLAUDE_MODELS["sonnet"]
    config(tmp_path, models={"codex": "test-model"})
    assert ai.select(tmp_path, "briefing-chat").provider == "codex"
    assert ai.select(tmp_path, "briefing-chat").model == "test-model"
    assert ai.select(tmp_path, "task-review").provider == "claude"
    assert ai.select(tmp_path, "arbitrary-worker").provider == "claude"
    assert ai.select(tmp_path, "briefing-chat", provider="claude").model == ai.CLAUDE_MODELS["haiku"]


@pytest.mark.parametrize("change", [{"provider": "typo"}, {"id": "wrong"}, {"command": "sh"},
                                    {"models": {"codex": "--evil"}}, {"models": {"other": "m"}},
                                    {"models": []}, {"schema_version": True}])
def test_bad_config_never_silently_uses_claude(tmp_path, change):
    path = config(tmp_path)
    data = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**data, **change}))
    with pytest.raises(ValueError):
        ai.select(tmp_path, "briefing-chat")


def test_path_traversal_and_symlinks(tmp_path):
    for service in ("../x", "_template", "foo/bar", "", None):
        with pytest.raises(ValueError):
            ai.load(tmp_path, service)
    path = config(tmp_path)
    outside = tmp_path / "outside.yaml"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        ai.load(tmp_path, "briefing-chat")


def test_codex_parser_requires_completion_and_never_invents_dollars():
    assert ai.parse_codex(events(completed=False)) is None
    got = ai.parse_codex("diagnostic\n" + events())
    assert got["text"] == "answer" and got["session"] == SID and got["total_usd"] is None
    assert got["usage"]["input_tokens"] == 5
    failed = events(completed=False) + '\n{"type":"turn.failed","error":{"message":"limit"}}'
    assert ai.parse_codex(failed)["error"] is True
    assert ai.parse_codex(failed)["text"] == "limit"


def test_readonly_allowlist_on_start_and_resume():
    for session in (None, SID):
        args = ai.codex_argv("/bin/codex", "--dangerously-bypass-approvals-and-sandbox", "test", session)
        assert ai.codex_argv_ok(args, "/bin/codex")
        assert args[-2] == "--"
        assert "read-only" in args and 'approval_policy="never"' in args
        for index, value in enumerate(args[:-2]):
            if value in ("read-only", "--ignore-user-config", "--ignore-rules", "hooks", "apps"):
                bad = args.copy()
                bad[index] = "bad"
                assert not ai.codex_argv_ok(bad, "/bin/codex")
        assert not ai.codex_argv_ok(args[:-2] + ["--dangerously-bypass-approvals-and-sandbox"] + args[-2:], "/bin/codex")
    with pytest.raises(ValueError):
        ai.codex_argv("codex", "hi", session="--last")


def test_worker_cli_resolves_without_a_model_call(tmp_path):
    config(tmp_path, "night-worker", "codex", {"codex": "test-model"})
    p = subprocess.run([sys.executable, str(ROOT / "scripts/ai-run.py"), "--root", str(tmp_path),
                        "--service", "night-worker", "--show"], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == {"service": "night-worker", "provider": "codex", "model": "test-model", "configured": True}


def test_review_provider_is_independent_and_normalizes_codex(tmp_path):
    spec = importlib.util.spec_from_file_location("ai_task_test", ROOT / "scripts/task.py")
    task = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(task)
    config(tmp_path, "task-review")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, events('[{"slug":"demo","verdict":"continue"}]'), "")
    result = task.ask_service(tmp_path, "task-review", task.DEFAULT_REVIEW_COMMAND, "codex-default", "prompt", run, 10)
    assert result["ok"] and result["items"][0]["slug"] == "demo" and result["cost"] is None
    assert calls[0][0][0] == "codex" and "shell_tool" in calls[0][0]
    assert "--model" not in calls[0][0]
    assert task.service_model(tmp_path, "triage", "sonnet") == ai.CLAUDE_MODELS["sonnet"]


def test_template_matches_schema():
    jsonschema = pytest.importorskip("jsonschema")
    folder = ROOT / "workflow/ai-services"
    jsonschema.validate(yaml.safe_load((folder / "_template.yaml").read_text()),
                        yaml.safe_load((folder / "_schema.yaml").read_text()))
