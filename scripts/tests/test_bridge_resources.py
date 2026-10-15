# SPDX-License-Identifier: MIT
"""scripts/bridge-resources.py: machines, workers and accounts of a Bridge as briefing rows.

A fake Bridge in a temp folder, tailscale and ssh injected: nothing leaves the test."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("bridge_resources", ROOT / "scripts" / "bridge-resources.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)
TX = br.TX["en"]
TODAY = dt.date(2026, 10, 10)
NOW = dt.datetime(2026, 10, 10, 14, 0, tzinfo=dt.timezone.utc)


def bridge(tmp: Path) -> Path:
    (tmp / "infra" / "remotes").mkdir(parents=True)
    (tmp / "identity" / "accounts").mkdir(parents=True)
    (tmp / "infra" / "remotes" / "_template.yaml").write_text("name: template\n")
    (tmp / "infra" / "remotes" / "box.yaml").write_text(
        "name: box\ntype: macos\nos: macOS 27\nnetwork: {tailscale_hostname: box}\ncapabilities: [ssh, arm]\n")
    (tmp / "infra" / "remotes" / "laptop.yaml").write_text("name: laptop\ntype: macos\n")
    (tmp / "infra" / "remotes" / "printer.yaml").write_text("name: printer\ntype: 3d-printer\n")
    (tmp / "infra" / "remotes" / "broken.yaml").write_text("name: [unclosed\n")
    acc = tmp / "identity" / "accounts"
    (acc / "azure-x.yaml").write_text(
        "id: azure-x\ndisplay_name: Azure X\nowner: me\nstatus: active\n"
        "tenant: {portal_url: 'https://portal.azure.com/#@x'}\nsubscriptions: [{id: a}, {id: b}]\n"
        "resource_groups: [{name: r}]\nsnapshot: {last_verified: 2026-09-30}\n")
    (acc / "cf-x.yaml").write_text(
        "id: cf-x\ndisplay_name: Cloudflare X\nstatus: active\n"
        "cloud: {provider: cloudflare, dashboard_url: 'https://dash.cloudflare.com/x', zones: [{name: x.com}]}\n")
    (acc / "mail-x.yaml").write_text("id: mail-x\ndisplay_name: Mail X\nmail: {provider: google}\n")
    (acc / "old-x.yaml").write_text(
        "id: old-x\ndisplay_name: Old Registrar\nstatus: legacy\nregistrar: {provider: godaddy, dashboard_url: 'http://plain'}\n")
    return tmp


def test_machines_are_live_from_tailscale_and_an_always_on_one_offline_is_red(tmp_path):
    root = bridge(tmp_path)
    rows = br.machine_rows(root, TX, {"box": {"online": False, "last_seen": "2026-10-10T12:00:00Z"},
                                      "laptop": {"online": True, "last_seen": None}})
    by = {r["title"]: r for r in rows}
    assert set(by) == {"box", "laptop", "printer"}                   # _template and a broken file are skipped
    assert by["box"]["tone"] == "bad" and "always on" in by["box"]["raw_state"] and "last seen" in by["box"]["raw_state"]
    assert by["laptop"]["tone"] == "none" and "online" in by["laptop"]["raw_state"]
    assert by["printer"]["tone"] == "dim"                            # not in the tailnet: nothing live to say
    assert [r["title"] for r in rows][0] == "box"                    # always-on machines first
    assert "tailscale not readable" in br.machine_rows(root, TX, None)[0]["raw_state"]


def test_tailscale_peers_reads_hostnames_and_self(monkeypatch):
    out = json.dumps({"Self": {"HostName": "Me", "Online": False},
                      "Peer": {"k": {"HostName": "DevBox", "DNSName": "devbox.tail.ts.net.", "Online": True, "LastSeen": "x"}}})
    run = lambda argv, **kw: types.SimpleNamespace(returncode=0, stdout=out)     # noqa: E731
    # through monkeypatch: br.shutil is the shutil module, a plain assignment would leak into every later test
    monkeypatch.setattr(br.shutil, "which", lambda name: "/x/tailscale")
    peers = br.tailscale_peers(run)
    assert peers["devbox"]["online"] is True and peers["me"]["online"] is True


def test_accounts_carry_provider_resources_age_and_a_safe_portal_link(tmp_path):
    rows = br.account_rows(bridge(tmp_path), TX, TODAY)
    by = {r["title"]: r for r in rows}
    assert [r["title"] for r in rows][:2] == ["Azure X", "Cloudflare X"]         # cloud first, inactive last
    assert rows[-1]["title"] == "Old Registrar" and rows[-1]["tone"] == "dim"
    assert "2 subscriptions" in by["Azure X"]["raw_state"] and "checked 10 d ago" in by["Azure X"]["raw_state"]
    assert by["Azure X"]["url"] == "https://portal.azure.com/#@x"
    assert "1 zones" in by["Cloudflare X"]["raw_state"] and "never checked" in by["Cloudflare X"]["raw_state"]
    assert by["Old Registrar"]["raw_state"].startswith("godaddy") and "url" not in by["Old Registrar"] or not by["Old Registrar"]["url"]


def report(*findings):
    return {"header": "x", "exit_code": 1, "findings": [
        {"workload_id": w, "state": s, "severity": "", "detail": f"{w} {s}"} for w, s in findings]}


def test_workers_list_only_what_needs_a_look_worst_first(tmp_path):
    src = tmp_path / "w.json"
    src.write_text(json.dumps({"schema": 1, "host": "box", "at": "2026-10-10T13:30:00+00:00", "report": report(
        ("a", "in_sync"), ("b", "drifted"), ("b", "in_sync"), ("c", "absent"), ("c", "disabled"), ("d", "unmanaged"),
        ("e", "inventory_stale"), ("f", "intentionally_absent"))}))
    rows = br.worker_rows(TX, str(src), NOW, 70)
    assert rows[0]["title"] == "2 of 4 workers on box in order" and rows[0]["meter"] == {"value": 2, "max": 4, "unit": None}
    assert rows[0]["tone"] == "none" and "as of" in rows[0]["raw_state"]
    assert [(r["title"], r["tone"]) for r in rows[1:]] == [("c", "bad"), ("b", "warn"), ("e", "warn")]


def test_an_old_report_warns_and_a_missing_one_is_red(tmp_path):
    src = tmp_path / "w.json"
    src.write_text(json.dumps({"host": "box", "at": "2026-10-10T11:00:00+00:00", "report": report(("a", "in_sync"))}))
    rows = br.worker_rows(TX, str(src), NOW, 70)
    assert rows[0]["tone"] == "warn" and "180 min old" in rows[0]["raw_state"]
    assert br.worker_rows(TX, str(tmp_path / "missing.json"), NOW, 70)[0]["tone"] == "bad"


def test_workers_come_over_ssh_with_a_fixed_argv():
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"host": "box", "report": report()}), stderr="")

    data, err = br.read_source("ssh:box:~/.bridge/resources/workloads.json", run)
    assert err is None and data["host"] == "box"
    assert seen["argv"] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "box", "cat ~/.bridge/resources/workloads.json"]
    br.read_source("ssh:box:/x/it's.json", run)
    assert seen["argv"][-1] == "cat '/x/it'\"'\"'s.json'"
    assert br.read_source("ssh:bad host;rm:/x", run) == (None, "bad source")


def test_stamp_wraps_a_report_even_with_a_line_after_it(tmp_path):
    raw = tmp_path / "r.json"
    raw.write_text(json.dumps(report(("a", "in_sync"))) + "\nnotify: 0 message(s) out\n")
    out = tmp_path / "res" / "workloads.json"
    assert br.stamp(raw, "box", "2026-10-10T14:00:00+02:00", out) == 0
    data = json.loads(out.read_text())
    assert data["host"] == "box" and data["at"].startswith("2026-10-10") and data["report"]["findings"][0]["workload_id"] == "a"
    raw.write_text("[1, 2]")
    assert br.stamp(raw, "box", "x", out) == 2


def test_overview_is_one_gauge_row_per_family(tmp_path):
    root = bridge(tmp_path)
    src = tmp_path / "w.json"
    src.write_text(json.dumps({"host": "box", "at": "2026-10-10T13:30:00+00:00", "report": report(("a", "in_sync"), ("b", "absent"))}))
    rows = br.overview_rows(root, TX, TODAY, NOW, str(src), 70, {"box": {"online": True, "last_seen": None}})
    assert [r["id"] for r in rows] == ["overview:workers", "overview:machines", "overview:accounts"]
    assert all(r["meter"]["max"] > 0 for r in rows)
    assert rows[1]["meter"] == {"value": 1, "max": 1, "unit": None}       # the one always-on machine is online
    assert rows[2]["meter"] == {"value": 1, "max": 3, "unit": None}       # one active account checked within 90 days
    (root / "identity" / "accounts" / "azure-x.yaml").write_text("id: azure-x\nstatus: active\n")    # nobody checks
    assert "overview:accounts" not in [r["id"] for r in br.overview_rows(root, TX, TODAY, NOW, None, 70, None)]


def test_listings_print_json_and_keep_a_copy_for_questions(tmp_path, capsys):
    root = bridge(tmp_path)
    assert br.main(["--root", str(root), "accounts"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and json.loads((root / ".bridge" / "resources" / "accounts.json").read_text()) == rows


def test_cloud_rows_head_each_account_and_tone_each_service(tmp_path):
    src = tmp_path / "c.json"
    src.write_text(json.dumps({"schema": 1, "host": "box", "at": "2026-10-10T13:30:00+00:00", "accounts": [
        {"id": "az", "display_name": "Azure X", "provider": "azure", "ok": True, "counts": {"sites": 3, "vaults": 2},
         "missing": [], "services": [
             {"name": "fn-a", "kind": "function app", "state": "running", "group": "rg", "url": "https://portal.azure.com/x"},
             {"name": "fn-b", "kind": "function app", "state": "stopped", "group": "rg", "url": "javascript:alert(1)"}]},
        {"id": "cf", "display_name": "Cloudflare X", "provider": "cloudflare", "ok": True, "counts": {"tunnels": 1},
         "missing": ["/pages: HTTP 403"], "services": [{"name": "t1", "kind": "tunnel", "state": "down"}]},
        {"id": "aws", "display_name": "AWS X", "provider": "aws", "ok": False, "error": "no inventory for provider aws yet"}]}))
    rows = br.cloud_rows(TX, str(src), NOW, 150)
    by = {r["id"]: r for r in rows}
    head = by["cloud:az"]
    assert "5 resources" in head["raw_state"] and "2 apps: 1 running, 1 stopped" in head["raw_state"]
    assert head["meter"] == {"value": 1, "max": 2, "unit": None} and head["tone"] == "none"
    assert by["cloud:az:function app:fn-a"]["tone"] == "none" and by["cloud:az:function app:fn-a"]["url"] == "https://portal.azure.com/x"
    assert by["cloud:az:function app:fn-b"]["tone"] == "dim" and not by["cloud:az:function app:fn-b"]["url"]
    assert by["cloud:cf"]["tone"] == "warn" and "partly" in by["cloud:cf"]["raw_state"]
    assert by["cloud:cf:tunnel:t1"]["tone"] == "bad"
    assert by["cloud:aws"]["tone"] == "bad" and "not readable" in by["cloud:aws"]["raw_state"]
    assert br.cloud_rows(TX, str(tmp_path / "none.json"), NOW, 150)[0]["tone"] == "bad"


def test_the_full_worker_view_becomes_mosaic_rows_and_is_kept_whole(tmp_path):
    src = tmp_path / "v.json"
    doc = {"schema": 1, "host": "box", "generated_at": "2026-10-10T13:30:00+00:00", "runs": [
        {"id": "a", "title": "Mail watcher", "purpose": "checks mail", "state": "in_sync", "findings": []},
        {"id": "b", "title": "Pilot", "purpose": "drives the board", "state": "absent",
         "findings": [{"state": "absent", "severity": "high", "detail": "gone", "hint": "provision"}]},
        {"id": "c", "title": "Old", "state": "absent", "retired": True}]}
    src.write_text(json.dumps(doc))
    rows = br.view_rows(tmp_path, TX, str(src), NOW, 70)
    assert rows[0]["title"] == "1 of 2 workers on box in order"
    assert [(r["title"], r["tone"]) for r in rows[1:]] == [("Pilot", "bad"), ("Mail watcher", "none")]
    assert "gone" in rows[1]["raw_state"] and "checks mail" in rows[2]["raw_state"]
    assert json.loads((tmp_path / ".bridge" / "resources" / "workers-view.json").read_text()) == doc
    assert br.view_rows(tmp_path, TX, str(tmp_path / "nope.json"), NOW, 70)[0]["tone"] == "bad"


def test_rows_carry_tags_to_filter_by_and_accounts_their_status(tmp_path):
    rows = br.account_rows(bridge(tmp_path), TX, TODAY)
    by = {r["title"]: r for r in rows}
    assert by["Azure X"]["account"] == {"id": "azure-x", "status": "active"}
    assert by["Old Registrar"]["tags"] == {"Provider": "godaddy", "Status": "legacy"}
    assert by["Mail X"]["account"]["status"] == "active"           # no status line means active


def test_set_status_rewrites_one_line_and_keeps_the_old_note(tmp_path):
    root = bridge(tmp_path)
    path = root / "identity" / "accounts" / "azure-x.yaml"
    path.write_text(path.read_text().replace("status: active", "status: active   # Kunde aktiv"))
    before = path.read_text()
    assert br.set_status(root, "azure-x", "disabled", TODAY) == 0
    after = path.read_text()
    assert "status: disabled    # 2026-10-10 set in the dashboard, was active: Kunde aktiv" in after
    assert after.replace(after.splitlines()[3], "") == before.replace(before.splitlines()[3], "")   # only that line
    assert br.set_status(root, "azure-x", "disabled", TODAY) == 0                 # again: nothing to do
    # no status line yet: one comes after `id:`
    assert br.set_status(root, "mail-x", "paused", TODAY) == 0
    assert (root / "identity" / "accounts" / "mail-x.yaml").read_text().splitlines()[1].startswith("status: paused")
    # never anything else
    assert br.set_status(root, "azure-x", "legacy", TODAY) == 2
    assert br.set_status(root, "../etc", "disabled", TODAY) == 2
    assert br.set_status(root, "nobody", "disabled", TODAY) == 2


def test_cloud_services_get_readable_kind_and_state_as_tags(tmp_path):
    src = tmp_path / "c.json"
    src.write_text(json.dumps({"schema": 1, "host": "box", "at": "2026-10-10T13:30:00+00:00", "accounts": [
        {"id": "az", "display_name": "Azure X", "provider": "azure", "ok": True, "counts": {"vaults": 1}, "missing": [],
         "services": [{"name": "kv", "kind": "vaults", "type": "Microsoft.KeyVault/vaults", "state": "present",
                       "group": "rg", "location": "westeurope"}]}]}))
    rows = br.cloud_rows(TX, str(src), NOW, 150)
    assert rows[0]["account"] == {"id": "az"}
    kv = rows[1]
    assert kv["tone"] == "none" and kv["tags"] == {"Kind": "Key Vault", "State": "present", "Resource group": "rg",
                                                    "Region": "westeurope"}


def test_a_cloud_service_names_the_declaration_that_knows_it_and_a_retired_one_is_not_red(tmp_path):
    root = bridge(tmp_path)
    wl = root / "workflow" / "workloads"
    wl.mkdir(parents=True)
    (wl / "gw-tunnel.yaml").write_text("id: gw-tunnel\npurpose: tunnel\nsecrets: [cf-tunnel-gw-old]\n"
                                       "hint: 'Tunnel-Objekt bei Cloudflare: gw-old'\nretired:\n  at: '2026-09-05T08:35:04+02:00'\n  reason: weg\n")
    (wl / "agent-tunnel.yaml").write_text("id: agent-tunnel\nhint: 'Tunnel agent-live'\n")
    src = tmp_path / "c.json"
    src.write_text(json.dumps({"schema": 1, "host": "box", "at": "2026-10-10T13:30:00+00:00", "accounts": [
        {"id": "cf", "display_name": "CF", "provider": "cloudflare", "ok": True, "counts": {"tunnels": 3}, "missing": [], "services": [
            {"name": "gw-old", "kind": "tunnel", "state": "down"}, {"name": "agent-live", "kind": "tunnel", "state": "healthy"},
            {"name": "stranger", "kind": "tunnel", "state": "down"}]}]}))
    by = {r["title"]: r for r in br.cloud_rows(TX, str(src), NOW, 150, root=root)}
    assert by["gw-old"]["tone"] == "dim" and "retired 05.09." in by["gw-old"]["raw_state"]
    assert by["gw-old"]["tags"]["Known from"] == "gw-tunnel"
    assert by["agent-live"]["tags"]["Known from"] == "agent-tunnel" and by["agent-live"]["tone"] == "none"
    assert by["stranger"]["tone"] == "bad" and by["stranger"]["tags"]["Known from"] == "nowhere"
