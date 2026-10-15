# SPDX-License-Identifier: MIT
"""The knowledge graph of the cockpit's inner room: which config entry names which."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from bridge_cockpit import graph  # noqa: E402


def put(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def tree(tmp_path: Path) -> Path:
    put(tmp_path, "bridge-config.yaml", "identity:\n  name: x\n")
    put(tmp_path, "identity/personas/me.yaml", "display_name: Me as a freelancer\n")
    put(tmp_path, "identity/personas/_template.yaml", "persona_ref: me\n")
    put(tmp_path, "identity/mandants/box.yaml", "name: a mandant that shares the remote's id\n")
    put(tmp_path, "infra/remotes/box.yaml", "name: box\nstatus: online\n")
    put(tmp_path, "workflow/workloads/job.yaml",
        "description: nightly job\npersona_ref: me\nhost: box\ncheck_ref: nowhere\n"
        "docs: docs/job.md\nmissing: docs/gone.md\nurl: https://example.org/a/b.md\n")
    put(tmp_path, "docs/job.md", "# job\n")
    put(tmp_path, "work/tasks/alpha/STATUS.md",
        "# yaml-language-server: $schema=x\n---\nslug: alpha\nstatus: doing\nheadline: The alpha task\n"
        "related:\n  - ../../../docs/job.md\n  - ../../../docs/gone.md\n---\n\n# Alpha\n")
    put(tmp_path, "infra/backups/topology.yaml", "---\nsources:\n  - host: box\n---\nmore: 1\n")
    return tmp_path


def test_nodes_edges_and_how_references_resolve(tmp_path):
    g = graph.build(tree(tmp_path))
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = {(e["s"], e["t"]): e for e in g["edges"]}
    # templates stay out; a task is a node with its headline and status
    assert "identity/personas/_template.yaml" not in nodes
    assert nodes["work/tasks/alpha/STATUS.md"]["label"] == "alpha"
    assert nodes["work/tasks/alpha/STATUS.md"]["title"] == "The alpha task"
    assert nodes["infra/remotes/box.yaml"]["status"] == "online"
    # an id reference finds the family its key names, even where another family has the same id
    assert edges[("workflow/workloads/job.yaml", "identity/personas/me.yaml")]["kind"] == "ref"
    assert ("workflow/workloads/job.yaml", "infra/remotes/box.yaml") in edges
    assert ("workflow/workloads/job.yaml", "identity/mandants/box.yaml") not in edges
    # a path that exists is an edge, and its file a leaf node; a dead path, a URL, an unknown id are none
    assert edges[("workflow/workloads/job.yaml", "docs/job.md")]["kind"] == "path"
    assert nodes["docs/job.md"].get("leaf") is True
    assert "docs/gone.md" not in nodes
    assert not any(t == "nowhere" or t.startswith("http") for _, t in edges)
    # a task's front matter points relative to its folder
    assert ("work/tasks/alpha/STATUS.md", "docs/job.md") in edges
    # a multi-document file is read by its first document
    assert ("infra/backups/topology.yaml", "infra/remotes/box.yaml") in edges
    assert nodes["infra/remotes/box.yaml"]["degree"] == 2


def test_a_node_hands_out_its_text_only_inside_the_graph(tmp_path):
    root = tree(tmp_path)
    put(root, "secret.txt", "not a node\n")
    g = graph.Graph(root)
    found = g.node("workflow/workloads/job.yaml")
    assert "nightly job" in found["text"] and found["cut"] is False
    assert {e["t"] for e in found["out"]} == {"identity/personas/me.yaml", "infra/remotes/box.yaml", "docs/job.md"}
    assert graph.Graph(root).node("docs/job.md")["in"][0]["s"] in ("workflow/workloads/job.yaml", "work/tasks/alpha/STATUS.md")
    assert g.node("secret.txt") is None
    assert g.node("../etc/passwd") is None


def test_the_graph_is_kept_a_minute(tmp_path):
    root = tree(tmp_path)
    now = [0.0]
    g = graph.Graph(root, clock=lambda: now[0])
    first = g.view()
    put(root, "infra/remotes/other.yaml", "name: other\n")
    assert g.view() is first
    now[0] = 61
    assert any(n["id"] == "infra/remotes/other.yaml" for n in g.view()["nodes"])


def test_a_name_several_files_share_carries_its_family(tmp_path):
    # acme as a context and as a mandant: the room and its search must tell them apart
    for rel in ("workflow/contexts/acme.yaml", "identity/mandants/acme.yaml", "workflow/contexts/solo.yaml"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("name: x\n")
    labels = sorted(n["label"] for n in graph.build(tmp_path)["nodes"])
    assert labels == ["acme (contexts)", "acme (mandants)", "solo"]
