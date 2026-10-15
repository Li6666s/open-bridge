# SPDX-License-Identifier: MIT
"""scripts/cloud-inventory.py: what runs in opted-in cloud accounts, read only.
az, the keychain and the Cloudflare API are injected: nothing leaves the test."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("cloud_inventory", ROOT / "scripts" / "cloud-inventory.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def bridge(tmp: Path) -> Path:
    acc = tmp / "identity" / "accounts"
    acc.mkdir(parents=True)
    (acc / "_template.yaml").write_text("inventory: {enabled: true}\n")
    (acc / "azure-x.yaml").write_text(
        "id: azure-x\ndisplay_name: Azure X\ntenant: {primary_domain: x.com}\n"
        "subscriptions: [{id: s1, display_name: One}, {id: s2, display_name: Two}]\ninventory: {enabled: true}\n")
    (acc / "cf-x.yaml").write_text(
        "id: cf-x\ndisplay_name: CF X\ncloud: {provider: cloudflare, account_id: abc}\n"
        "inventory: {enabled: true, token_ref: 'keychain://cf-inv/claude'}\n")
    (acc / "quiet.yaml").write_text("id: quiet\ncloud: {provider: azure}\n")           # not opted in: never asked
    (acc / "azure-off.yaml").write_text(                                               # switched off: never asked
        "id: azure-off\nstatus: disabled\ntenant: {primary_domain: o.com}\nsubscriptions: [{id: s1}]\ninventory: {enabled: true}\n")
    return tmp


def fake_az(argv, **kw):
    out = {("account", "list"): [{"id": "s1"}],
           ("resource", "list"): [{"name": "fn-a", "type": "Microsoft.Web/sites", "group": "rg", "location": "westeurope", "id": "/subs/s1/x"},
                                  {"name": "web-b", "type": "Microsoft.Web/sites", "group": "rg", "id": "/subs/s1/y"},
                                  {"name": "kv", "type": "Microsoft.KeyVault/vaults", "group": "rg", "id": "/subs/s1/k"}],
           # as the real CLI does: webapp list leaves function apps out, functionapp list has only them
           ("webapp", "list"): [{"state": "Stopped", "kind": "app", "id": "/subs/s1/y"}],
           ("functionapp", "list"): [{"state": "Running", "kind": "functionapp,linux", "id": "/SUBS/s1/x"}]}
    if argv[0] == "/usr/bin/security":
        return types.SimpleNamespace(returncode=0, stdout="tok\n", stderr="")
    return types.SimpleNamespace(returncode=0, stdout=json.dumps(out[tuple(argv[1:3])]), stderr="")


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_cf(req, timeout=0):
    assert req.headers["Authorization"] == "Bearer tok" and req.get_method() == "GET"
    path = req.full_url.split("/v4", 1)[1].split("?")[0]
    result = {"/zones": [{"name": "x.com", "status": "active"}], "/accounts/abc/workers/scripts": [{"id": "w1"}],
              "/accounts/abc/pages/projects": [{"name": "site", "latest_deployment": {"latest_stage": {"status": "success"}}}],
              "/accounts/abc/cfd_tunnel": [{"name": "t1", "status": "healthy"}]}[path]
    return Resp(json.dumps({"success": True, "result": result}).encode())


def test_only_opted_in_accounts_are_asked_and_each_says_what_runs(tmp_path):
    out = ci.inventory(bridge(tmp_path), run=fake_az, opener=fake_cf)
    by = {a["id"]: a for a in out}
    assert set(by) == {"azure-x", "cf-x"}
    az = by["azure-x"]
    assert az["ok"] and az["counts"] == {"sites": 2, "vaults": 1} and az["missing"] == ["Two"]
    # every resource, a site with its state (ids compared without case), the rest as present
    assert [(s["name"], s["kind"], s["state"]) for s in az["services"]] == [
        ("fn-a", "function app", "running"), ("kv", "vaults", "present"), ("web-b", "web app", "stopped")]
    assert az["services"][0]["location"] == "westeurope" and az["services"][1]["type"] == "Microsoft.KeyVault/vaults"
    assert az["services"][0]["url"] == "https://portal.azure.com/#@x.com/resource/subs/s1/x"
    cf = by["cf-x"]
    assert cf["ok"] and cf["counts"] == {"zones": 1, "workers": 1, "pages": 1, "tunnels": 1}
    assert {s["kind"]: s["state"] for s in cf["services"]} == {"zone": "active", "worker": "deployed", "pages": "success", "tunnel": "healthy"}


def test_a_failing_account_says_why_and_the_others_still_come(tmp_path):
    root = bridge(tmp_path)
    no_key = lambda argv, **kw: (types.SimpleNamespace(returncode=44, stdout="", stderr="")      # noqa: E731
                                 if argv[0] == "/usr/bin/security" else fake_az(argv))
    by = {a["id"]: a for a in ci.inventory(root, run=no_key, opener=fake_cf)}
    assert by["azure-x"]["ok"] is True
    assert by["cf-x"]["ok"] is False and "no token in the keychain" in by["cf-x"]["error"]


def test_main_writes_one_stamped_file_atomically(tmp_path, monkeypatch):
    root = bridge(tmp_path)
    monkeypatch.setattr(ci, "inventory", lambda r: [{"id": "a", "ok": True}])
    out = tmp_path / "res" / "cloud.json"
    assert ci.main(["--root", str(root), "--host", "box", "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["schema"] == 1 and data["host"] == "box" and data["accounts"] == [{"id": "a", "ok": True}]
    assert not list(out.parent.glob(".*.tmp"))


def test_cloudflare_zones_are_read_page_by_page():
    seen = []

    def opener(req, timeout=0):
        page = int(req.full_url.split("page=")[-1])
        seen.append(page)
        result = [{"name": f"z{page}-{i}"} for i in range(50 if page == 1 else 3)]
        return Resp(json.dumps({"success": True, "result": result}).encode())
    assert len(ci.cf_pages("/zones?account.id=a", "tok", opener)) == 53 and seen == [1, 2]
