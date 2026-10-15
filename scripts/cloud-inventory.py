#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What runs in the cloud accounts right now, read only, for the dashboard's Resources page.

    cloud-inventory.py --host H --out FILE [--root R]

Runs on the always-on machine, once an hour (a workload). Asks only the accounts in
identity/accounts/*.yaml that opt in with

    inventory:
      enabled: true
      token_ref: keychain://<service>/<account>     # providers that need a token (cloudflare)

and writes one stamped JSON file ({schema, host, at, accounts: [...]}) atomically, which
scripts/bridge-resources.py turns into rows (`cloud --source`). Every call only reads:

- azure: the logged-in `az` CLI, per declared subscription `az resource list` (every resource with its
  type, group and region, counted by type) and `az webapp list` plus `az functionapp list`, which give web
  and function apps their state. A subscription the CLI does not see is reported, never guessed.
- cloudflare: the REST API with a read-only token from the keychain reference: zones, Workers
  scripts, Pages projects (latest deployment), tunnels (status).

An account that fails says why in its entry; the others still come. Nothing here writes to a
provider, and a token is read only to make the calls, never stored or printed.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
CF_API = "https://api.cloudflare.com/client/v4"
TIMEOUT = 40


def accounts(root: Path) -> list[dict]:
    out = []
    for path in sorted((root / "identity" / "accounts").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        inv = data.get("inventory") if isinstance(data, dict) else None
        # an account set to anything but active (paused, disabled, legacy) is not asked
        if isinstance(inv, dict) and inv.get("enabled") is True and str(data.get("status") or "active") == "active":
            out.append(data)
    return out


def provider_of(acc: dict) -> str:
    cloud = acc.get("cloud") if isinstance(acc.get("cloud"), dict) else {}
    if cloud.get("provider"):
        return str(cloud["provider"])
    if isinstance(acc.get("tenant"), dict) or isinstance(acc.get("subscriptions"), list):
        return "azure"
    return str(acc.get("id", "")).split("-")[0]


# ---------------------------------------------------------------- azure

def run_json(argv: list[str], run: Callable = subprocess.run) -> Any:
    res = run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    if res.returncode != 0:
        raise RuntimeError(((res.stderr or res.stdout or "").strip().splitlines() or ["failed"])[-1][:200])
    return json.loads(res.stdout or "null")


def azure(acc: dict, run: Callable = subprocess.run, opener: Callable | None = None) -> dict:
    tenant = acc.get("tenant") if isinstance(acc.get("tenant"), dict) else {}
    domain = tenant.get("primary_domain") or ""
    visible = {s.get("id") for s in (run_json(["az", "account", "list", "-o", "json"], run) or []) if isinstance(s, dict)}
    subs = [s for s in (acc.get("subscriptions") or []) if isinstance(s, dict) and s.get("id")]
    counts: collections.Counter = collections.Counter()
    services, missing = [], []
    for sub in subs:
        sid = sub["id"]
        if sid not in visible:
            missing.append(sub.get("display_name") or sub.get("name") or sid)
            continue
        resources = run_json(["az", "resource", "list", "--subscription", sid, "--query",
                              "[].{name:name,type:type,group:resourceGroup,location:location,id:id}", "-o", "json"], run) or []
        # `az webapp list` leaves function apps out, so both lists; they give a site its state
        sites = {}
        for verb in ("webapp", "functionapp"):
            for site in run_json(["az", verb, "list", "--subscription", sid, "--query",
                                  "[].{state:state,kind:kind,id:id}", "-o", "json"], run) or []:
                sites.setdefault(str(site.get("id") or "").lower(), site)
        for r in resources:
            rtype = str(r.get("type") or "?")
            counts[rtype.split("/", 1)[-1]] += 1
            site = sites.get(str(r.get("id") or "").lower())
            if site is not None:
                kind = "function app" if "functionapp" in str(site.get("kind") or "") else "web app"
                state = str(site.get("state") or "?").lower()
            else:
                kind, state = rtype.split("/")[-1].lower(), "present"
            url = f"https://portal.azure.com/#@{domain}/resource{r['id']}" if domain and r.get("id") else None
            services.append({"name": r.get("name"), "kind": kind, "type": rtype, "state": state,
                             "group": r.get("group"), "location": r.get("location"), "url": url})
    if not subs:
        raise RuntimeError("no subscriptions declared")
    if missing and len(missing) == len(subs):
        raise RuntimeError("the az CLI sees none of the declared subscriptions: " + ", ".join(map(str, missing)))
    return {"counts": dict(counts), "services": sorted(services, key=lambda x: (x["kind"], str(x["name"] or "").lower())),
            "missing": missing}


# ---------------------------------------------------------------- cloudflare

def keychain(ref: str, run: Callable = subprocess.run) -> str:
    if not isinstance(ref, str) or not ref.startswith("keychain://") or ref.count("/") != 3:
        raise RuntimeError("no token_ref (keychain://<service>/<account>) in inventory")
    service, account = ref[len("keychain://"):].split("/", 1)
    res = run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
              capture_output=True, text=True, timeout=10)
    if res.returncode != 0 or not res.stdout.strip():
        raise RuntimeError(f"no token in the keychain under {service}/{account}")
    return res.stdout.strip()


def cf_get(path: str, token: str, opener: Callable = urllib.request.urlopen) -> Any:
    req = urllib.request.Request(CF_API + path, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with opener(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path.split('?')[0]}: HTTP {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"{path.split('?')[0]}: {e}")
    if not body.get("success", False):
        raise RuntimeError(f"{path.split('?')[0]}: {((body.get('errors') or [{}])[0]).get('message', 'failed')}")
    return body.get("result")


def cf_pages(path: str, token: str, opener: Callable = urllib.request.urlopen, cap: int = 20) -> list:
    """Every page of a paged list (`page=`, 50 per page) until one comes back short; at most `cap` pages."""
    out: list = []
    for page in range(1, cap + 1):
        part = cf_get(f"{path}{'&' if '?' in path else '?'}per_page=50&page={page}", token, opener) or []
        out += part
        if len(part) < 50:
            break
    return out


def cloudflare(acc: dict, run: Callable = subprocess.run, opener: Callable = urllib.request.urlopen) -> dict:
    cloud = acc.get("cloud") if isinstance(acc.get("cloud"), dict) else {}
    aid = cloud.get("account_id")
    if not aid:
        raise RuntimeError("no cloud.account_id declared")
    token = keychain((acc.get("inventory") or {}).get("token_ref"), run)
    dash = f"https://dash.cloudflare.com/{aid}"
    services, counts, errors = [], collections.Counter(), []

    def part(fn):
        try:
            fn()
        except RuntimeError as e:
            errors.append(str(e))

    def zones():
        for z in cf_pages(f"/zones?account.id={aid}", token, opener):
            counts["zones"] += 1
            services.append({"name": z.get("name"), "kind": "zone", "state": str(z.get("status") or "?"),
                             "group": None, "url": f"{dash}/{z.get('name')}"})

    def workers():
        for w in cf_get(f"/accounts/{aid}/workers/scripts", token, opener) or []:
            counts["workers"] += 1
            services.append({"name": w.get("id"), "kind": "worker", "state": "deployed",
                             "group": (w.get("modified_on") or "")[:10] or None, "url": f"{dash}/workers/services/view/{w.get('id')}"})

    def pages():
        for p in cf_get(f"/accounts/{aid}/pages/projects", token, opener) or []:
            counts["pages"] += 1
            latest = p.get("latest_deployment") or {}
            stage = (latest.get("latest_stage") or {}).get("status") or "?"
            services.append({"name": p.get("name"), "kind": "pages", "state": stage,
                             "group": (latest.get("created_on") or "")[:10] or None, "url": f"{dash}/pages/view/{p.get('name')}"})

    def tunnels():
        for t in cf_get(f"/accounts/{aid}/cfd_tunnel?is_deleted=false", token, opener) or []:
            counts["tunnels"] += 1
            services.append({"name": t.get("name"), "kind": "tunnel", "state": str(t.get("status") or "?"),
                             "group": None, "url": f"https://one.dash.cloudflare.com/{aid}/networks/tunnels"})

    for fn in (zones, workers, pages, tunnels):
        part(fn)
    if errors and not services:
        raise RuntimeError("; ".join(errors)[:300])
    return {"counts": dict(counts), "services": services, "missing": errors}


PROVIDERS = {"azure": azure, "cloudflare": cloudflare}


def inventory(root: Path, run: Callable = subprocess.run, opener: Callable = urllib.request.urlopen) -> list[dict]:
    out = []
    for acc in accounts(root):
        prov = provider_of(acc)
        entry = {"id": acc.get("id"), "display_name": acc.get("display_name") or acc.get("id"), "provider": prov,
                 "ok": False, "error": None, "counts": {}, "services": [], "missing": []}
        fn = PROVIDERS.get(prov)
        try:
            if fn is None:
                raise RuntimeError(f"no inventory for provider {prov} yet")
            entry.update(fn(acc, run, opener))
            entry["ok"] = True
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
            entry["error"] = str(e)[:300]
        out.append(entry)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--host", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    data = {"schema": 1, "host": args.host, "at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "accounts": inventory(args.root.resolve())}
    out = args.out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name("." + out.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)
    bad = [a["id"] for a in data["accounts"] if not a["ok"]]
    print(f"cloud-inventory: {len(data['accounts'])} account(s), {len(bad)} failed" + (f": {', '.join(map(str, bad))}" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
