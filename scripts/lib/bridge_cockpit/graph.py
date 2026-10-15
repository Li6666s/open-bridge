# SPDX-License-Identifier: MIT
"""The Bridge's knowledge graph, for the inner room of the start page: which config entry names which.

Nodes are the config entries (the root *.yaml, identity/*/*.yaml, infra/*/*.yaml, workflow/*/*.yaml), the
open tasks and streams (work/tasks/<slug>/STATUS.md, work/streams/<slug>/STATUS.md), and every file one of
them points at that exists in the tree (a doc, a script). `_`-prefixed files (templates, schemas) and
examples stay out, as in scripts/check-edges.py.

Edges come in two shapes:

- path  a scalar that is a repo-relative path (the check-edges rule), or a path relative to a task's folder
        in its front matter (`related: ../../../docs/x.md`), resolving to a file that exists
- ref   a `*_ref`, `*_refs`, `related_*` value or a `host:` naming another entry by its id (`persona_ref:
        me` -> identity/personas/me.yaml). The family the key names wins
        (persona -> personas); otherwise only an id that is unique across the tree counts.

Read only. `node()` hands out a file's text, and only for a path that is a node of the graph.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import yaml

CONFIG_GLOBS = ("*.yaml", "identity/*/*.yaml", "infra/*/*.yaml", "workflow/*/*.yaml")
WORK_GLOBS = ("work/tasks/*/STATUS.md", "work/streams/*/STATUS.md")
PATH_RE = re.compile(r"^[a-z_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.@+-]+)+\.(?:yaml|yml|md|py|sh)$")
REL_RE = re.compile(r"^(?:\.\./)+[A-Za-z0-9_.@+/-]+\.(?:yaml|yml|md|py|sh)$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,80}$")
REF_KEY_RE = re.compile(r"^(?:(.+?)_refs?|related_(.+)|(host|hosts|remote|remotes|machine))$")
TITLE_KEYS = ("display_name", "title", "headline", "name", "description", "purpose", "summary")
TEXT_MAX = 8000
CACHE_S = 60

# the family a key's stem names; a stem not here may still match a family by its plural
FAMILY_OF = {
    "persona": "personas", "mandant": "mandants", "context": "contexts", "project": "projects",
    "account": "accounts", "contract": "contracts", "remote": "remotes", "remotes": "remotes", "host": "remotes",
    "hosts": "remotes", "machine": "remotes", "channel": "channels", "check": "checks", "vault": "secret-stores",
    "secret_store": "secret-stores", "workspace": "workspaces", "vehicle": "vehicles", "instance": "instances",
    "task": "tasks", "tasks": "tasks", "stream": "streams", "streams": "streams", "workload": "workloads",
    "meeting": "meetings", "briefing": "briefings", "peer": "a2a-peers", "utility": "utilities",
    "accounts": "accounts", "contracts": "contracts", "channels": "channels",
}


def _skip(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("_") or name.endswith(".example.yaml") or name.endswith(".lock.yaml") or "/examples/" in rel


def _family(rel: str) -> tuple[str, str]:
    """(group, family): the cluster wrapper (or work, core, docs, scripts) and the folder inside it"""
    parts = rel.split("/")
    if len(parts) == 1:
        return "core", "core"
    if parts[0] == "work" and len(parts) > 2:
        return "work", parts[1]
    if parts[0] in ("identity", "infra", "workflow") and len(parts) > 2:
        return parts[0], parts[1]
    return ("docs", parts[0]) if parts[0] in ("docs", "rules", "protocols", "skills") else ("other", parts[0])


def _label(rel: str) -> str:
    p = Path(rel)
    return p.parent.name if p.name == "STATUS.md" else p.stem


def _title(doc) -> str:
    if isinstance(doc, dict):
        for k in TITLE_KEYS:
            v = doc.get(k)
            if isinstance(v, str) and v.strip():
                return " ".join(v.split())[:160]
    return ""


def _front(text: str):
    """A Markdown file's YAML front matter (after an optional schema comment line), or None"""
    m = re.search(r"^---\s*\n(.*?)\n---\s*$", text, re.S | re.M)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None


def _load(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        return _front(text)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        # a multi-document file (infra/backups/topology.yaml): its first document
        try:
            docs = [d for d in yaml.safe_load_all(text) if d is not None]
        except yaml.YAMLError:
            return None
        return docs[0] if docs else None


def _walk(node, key: str, out: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(v, str(k), out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, key, out)
    elif isinstance(node, str):
        out.append((key, node.strip()))


def build(root: Path) -> dict:
    root = Path(root)
    files: list[str] = []
    for pattern in (*CONFIG_GLOBS, *WORK_GLOBS):
        for p in sorted(root.glob(pattern)):
            rel = p.relative_to(root).as_posix()
            if rel not in files and not _skip(rel):
                files.append(rel)
    nodes: dict[str, dict] = {}
    docs: dict[str, object] = {}
    for rel in files:
        try:
            doc = _load(root / rel)
        except (OSError, UnicodeDecodeError):
            continue
        group, family = _family(rel)
        docs[rel] = doc
        status = doc.get("status") if isinstance(doc, dict) and isinstance(doc.get("status"), str) else None
        nodes[rel] = {"id": rel, "group": group, "family": family, "label": _label(rel), "title": _title(doc),
                      "status": status}
    by_id: dict[str, list[str]] = {}
    for rel, n in nodes.items():
        by_id.setdefault(n["label"], []).append(rel)

    edges: dict[tuple[str, str], dict] = {}

    def add(src: str, dst: str, key: str, kind: str) -> None:
        if src == dst:
            return
        if dst not in nodes:
            group, family = _family(dst)
            nodes[dst] = {"id": dst, "group": group, "family": family, "label": _label(dst), "title": "",
                          "status": None, "leaf": True}
        edges.setdefault((src, dst), {"s": src, "t": dst, "key": key, "kind": kind})

    for rel, doc in docs.items():
        scalars: list = []
        _walk(doc, "", scalars)
        here = Path(rel).parent
        for key, value in scalars:
            if PATH_RE.match(value):
                if (root / value).is_file():
                    add(rel, value, key, "path")
                continue
            if REL_RE.match(value):
                target = (here / value).as_posix()
                parts: list[str] = []
                for seg in target.split("/"):
                    if seg == "..":
                        if not parts:
                            break
                        parts.pop()
                    elif seg not in ("", "."):
                        parts.append(seg)
                else:
                    dst = "/".join(parts)
                    if (root / dst).is_file():
                        add(rel, dst, key, "path")
                continue
            m = REF_KEY_RE.match(key)
            if not m or not ID_RE.match(value) or value not in by_id:
                continue
            stem = next(g for g in m.groups() if g)
            want = FAMILY_OF.get(stem) or FAMILY_OF.get(stem.rstrip("s"))
            cands = by_id[value]
            hit = [c for c in cands if nodes[c]["family"] == want] if want else []
            if not hit and len(cands) == 1 and not want:
                hit = cands
            for dst in hit[:1]:
                add(rel, dst, key, "ref")

    degree: dict[str, int] = {}
    for s, t in edges:
        degree[s] = degree.get(s, 0) + 1
        degree[t] = degree.get(t, 0) + 1
    # A name several files share (acme as a context, a mandant and a project, say) carries its family,
    # then its folder, so the room and its search tell them apart; references above resolved on the bare name.
    for widen in (lambda n: n["family"], lambda n: str(Path(n["id"]).parent)):
        seen: dict[str, list[dict]] = {}
        for n in nodes.values():
            seen.setdefault(n["label"], []).append(n)
        for same in seen.values():
            if len(same) > 1:
                for n in same:
                    n["label"] = f"{n['label'].split(' (')[0]} ({widen(n)})"
    out_nodes = [{**n, "degree": degree.get(n["id"], 0)} for n in nodes.values()]
    return {"nodes": out_nodes, "edges": list(edges.values())}


class Graph:
    """build() kept for a minute: the inner room opens often, the tree changes rarely"""

    def __init__(self, root: Path, clock=time.monotonic):
        self.root = Path(root)
        self.clock = clock
        self.lock = threading.Lock()
        self._at = None
        self._data = None

    def view(self) -> dict:
        with self.lock:
            if self._data is None or self.clock() - self._at > CACHE_S:
                self._data = build(self.root)
                self._at = self.clock()
            return self._data

    def node(self, rel: str) -> dict | None:
        """A node's text, cut, with its edges both ways; None for a path that is no node"""
        data = self.view()
        ids = {n["id"] for n in data["nodes"]}
        if rel not in ids:
            return None
        path = (self.root / rel).resolve()
        try:
            path.relative_to(self.root.resolve())
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError, UnicodeDecodeError):
            text = ""
        return {"id": rel, "text": text[:TEXT_MAX], "cut": len(text) > TEXT_MAX,
                "out": [e for e in data["edges"] if e["s"] == rel], "in": [e for e in data["edges"] if e["t"] == rel]}
