# SPDX-License-Identifier: MIT
"""The task check of the cockpit: `task.py review` in the background, its last result for the model.

A check reads every task in doing or review (or the named ones), asks a small model once for all of
them and a stronger one only for the unclear answers; it takes 20 s to three minutes. It runs on a
thread of its own, outside the write lock, so the page stays usable; one check at a time. The page
never waits for it: the model says `running`, and the finished check arrives as a note and a new
model. What the page shows comes from the last run that `task.py review` keeps in
.bridge/task-review.json (key `last`), read again only when the file changed.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from typing import Any

REVIEW_FILE = Path(".bridge") / "task-review.json"
# task.py stays inside 190 s for both model tiers; the evidence (one gh call) comes on top
REVIEW_TIMEOUT = 240
VERDICTS = ("close", "continue", "waiting", "stale", "unclear")
ROW_FIELDS = ("verdict", "reason", "confidence", "model", "kept", "resolved", "changed", "previous_verdict",
              "days_since_activity", "chips", "cached")


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _cents(usd: Any) -> float | None:
    if usd is None:
        return None
    try:
        return round(float(usd) * 100, 2)
    except (TypeError, ValueError):
        return None


def _short(model: str) -> str:
    return model.replace("claude-", "")


def _tiers(last: dict) -> dict:
    """Who answered how much in the last run, for the drawn check: per model the tasks it answered and what
    it cost, the cheaper tier first; tasks that came from the cache count apart. Every task of the run
    counts, also one closed since, because this is how the run went."""
    answered: dict[str, int] = {}
    cached = 0
    for t in _list(last.get("tasks")):
        if not isinstance(t, dict):
            continue
        if t.get("cached"):
            cached += 1
        elif isinstance(t.get("model"), str) and t["model"]:
            answered[_short(t["model"])] = answered.get(_short(t["model"]), 0) + 1
    costs = last.get("cost_by_model") if isinstance(last.get("cost_by_model"), dict) else {}
    cost = {_short(str(m)): _cents(usd) for m, usd in costs.items()}
    names = set(answered) | set(cost)
    tiers = [{"model": m, "answered": answered.get(m, 0), "cost_ct": cost.get(m)} for m in names]
    tiers.sort(key=lambda x: (x["cost_ct"] is None, x["cost_ct"] or 0, x["model"]))
    return {"tiers": tiers, "cached": cached}


class Review:
    def __init__(self, app: Any):
        self.app = app
        self.lock = threading.Lock()
        self.running: dict | None = None
        self.error: str | None = None
        self._cache: tuple[float, dict | None] = (-1.0, None)

    # ------------------------------------------------------------ reading

    def last(self) -> dict | None:
        """The last run as task.py saved it; None when there is none or the file is unreadable."""
        path = self.app.root / REVIEW_FILE
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        with self.lock:
            if self._cache[0] == mtime:
                return self._cache[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        last = data.get("last") if isinstance(data, dict) and isinstance(data.get("last"), dict) else None
        with self.lock:
            self._cache = (mtime, last)
        return last

    def state(self, is_open) -> dict:
        """The model's `review` block: running, the last run's numbers, one entry per task still open.
        A damaged cache file degrades to "no check yet", it never breaks the model."""
        with self.lock:
            running = dict(self.running) if self.running else None
            error = self.error
        out = {"running": running, "error": error, "last": None, "tasks": {}}
        try:
            return self._fill(out, self.last(), is_open)
        except (TypeError, AttributeError, ValueError) as exc:
            self.app.log_error(f"review: unreadable last run: {exc!r}")
            return {**out, "tasks": {}}

    def _fill(self, out: dict, last: dict | None, is_open) -> dict:
        if not last:
            return out
        tasks = {}
        for t in _list(last.get("tasks")):
            if not isinstance(t, dict):
                continue
            slug = t.get("slug")
            if not isinstance(slug, str) or not is_open(slug):
                continue      # closed since, or gone: nothing to act on
            entry = {k: t.get(k) for k in ROW_FIELDS}
            entry["verdict"] = entry["verdict"] if entry["verdict"] in VERDICTS else "unclear"
            for key in ("kept", "resolved", "changed", "cached"):
                entry[key] = bool(entry[key])
            for key in ("reason", "confidence", "model", "previous_verdict"):
                entry[key] = entry[key] if isinstance(entry[key], str) else None
            if not isinstance(entry["days_since_activity"], int):
                entry["days_since_activity"] = None
            entry["chips"] = [c for c in _list(entry["chips"]) if isinstance(c, dict)][:8]
            signals = t.get("signals") if isinstance(t.get("signals"), dict) else {}
            entry["closed_refs"] = [str(r) for r in _list(signals.get("closed_refs"))]
            entry["title"] = t["title"] if isinstance(t.get("title"), str) and t["title"] else slug
            entry["status"] = t.get("status") if isinstance(t.get("status"), str) else None
            entry["priority"] = t.get("priority") if isinstance(t.get("priority"), str) else None
            tasks[slug] = entry
        out["tasks"] = tasks
        out["last"] = {"reviewed_at": last.get("reviewed_at"), "reviewed": last.get("reviewed"),
                       "to_close": sum(1 for x in tasks.values()
                                       if (x["verdict"] == "close" or x["resolved"]) and not x["kept"]),
                       "cost_ct": _cents(last.get("cost_usd")), "cost_known": bool(last.get("cost_known", True)),
                       "models": [str(x).replace("claude-", "") for x in _list(last.get("models_used"))],
                       "duration_sec": last.get("duration_sec"),
                       "escalate_ct": _cents(last.get("escalate_call_usd")),
                       "mismatch": bool(last.get("model_mismatch")),
                       **_tiers(last)}
        return out

    # ------------------------------------------------------------ running

    def argv(self, slugs: list[str], escalate: bool, fresh: bool = False) -> list[str]:
        app = self.app
        return [sys.executable, app.runner.script("scripts/task.py"), "--root", str(app.root), "review", "--json",
                *(["--escalate"] if escalate else []), *(["--fresh"] if fresh and not escalate else []), *slugs]

    def open_count(self) -> int:
        """How many tasks a check of all of them asks about: the ones in doing or review, as task.py picks them"""
        n = 0
        for path in (Path(self.app.root) / "work" / "tasks").glob("*/STATUS.md"):
            if path.parent.name.startswith("_"):
                continue
            try:
                head = path.read_text(encoding="utf-8")[:4000]
            except (OSError, UnicodeDecodeError):
                continue
            if re.search(r"^status:\s*[\"']?(?:doing|review)\b", head, re.M):
                n += 1
        return n

    def start(self, slugs: list[str], escalate: bool, fresh: bool = False) -> bool:
        """Start a check on its own thread; False when one is running already. `fresh` asks again past the
        cache, which is what "check again" on one task means."""
        count = len(slugs) or self.open_count()
        with self.lock:
            if self.running:
                return False
            self.running = {"started_ms": int(self.app.clock()), "count": count, "escalate": escalate}
            self.error = None
        thread = threading.Thread(target=self._run, args=(list(slugs), escalate, fresh), name="bridge-cockpit-review",
                                  daemon=True)
        thread.start()
        return True

    def _run(self, slugs: list[str], escalate: bool, fresh: bool = False) -> None:
        app = self.app
        tx = app.tx
        try:
            run = app.run(self.argv(slugs, escalate, fresh), REVIEW_TIMEOUT)
            result = None
            if run.ok:
                try:
                    result = json.loads(run.out)
                except ValueError:
                    result = None
            if not isinstance(result, dict):
                result = None
                err = (run.err or "").strip().splitlines()[-1:] or ["no answer"]
                with self.lock:
                    self.error = app.scrub(err[0])[:200]
                app.note(tx["review_failed"].format(err=self.error), "bad")
            else:
                cost = (tx["review_cost"].format(ct=f"{_cents(result.get('cost_usd')):.2f}")
                        if result.get("cost_known", True) else tx["review_cost_unknown"])
                text = tx["review_done"].format(n=result.get("reviewed", 0), close=result.get("to_close", 0), cost=cost)
                if result.get("model_mismatch"):
                    text += " · " + tx["review_mismatch"]
                app.note(text, "ok")
        except Exception as exc:  # noqa: BLE001 - a failed check must never leave `running` set
            with self.lock:
                self.error = str(exc)[:200]
            app.log_error(f"review: {exc!r}")
            app.note(tx["review_failed"].format(err=self.error), "bad")
        finally:
            with self.lock:
                self.running = None
            app.collector.rebuild()
