"""Attach, detach or show this environment's Unity Gateway service policies (Beta, undocumented PATCH).

system.ai.* MCP services are metastore-wide. This script only adds or removes the policies named *_<BEV_ENV>
and keeps every other policy on the service untouched. Policy functions are bound by function id: after any
CREATE OR REPLACE of a policy function (run_setup.py --steps policies) run `attach` again, or the Gateway fails closed.
Usage: BEV_TARGET=<target> python setup/policies.py status|attach|detach [--service sql|m365|all] [--apply]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402

API = "/api/2.1/unity-catalog/mcp-services/"


def ours():
    fq = f"{C.CATALOG}.{C.SCHEMA}"
    return {"sql": ("system.ai.dbsql", f"bev_governed_sql_{C.ENV}", f"functions/{fq}.policy_agent_governed_sql"),
            "m365": ("system.ai.microsoft_365", f"bev_m365_docs_{C.ENV}", f"functions/{fq}.policy_m365_pricing_docs")}


def current(w, service):
    return (w.api_client.do("GET", API + service).get("config") or {}).get("service_policies") or []


def desired(existing, name, handler, attach):
    # a same-name entry pointing at another catalog/schema belongs to another environment: never take it over or remove it
    clash = [p for p in existing if p.get("name") == name and p.get("handler") != handler]
    if clash:
        raise SystemExit(f"policy {name} exists with handler {clash[0].get('handler')!r}, not {handler!r}: "
                         "another environment uses the same BEV_ENV. Pick a unique BEV_ENV.")
    keep = [p for p in existing if p.get("name") != name]
    if attach:
        rank = max([p.get("rank", 0) for p in keep] + [0]) + 1
        keep.append({"name": name, "policy_type": "POLICY_TYPE_CUSTOM", "handler": handler, "rank": rank})
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "attach", "detach"])
    ap.add_argument("--service", choices=["sql", "m365", "all"], default="all")
    ap.add_argument("--apply", action="store_true", help="write (default: show the change only)")
    a = ap.parse_args()
    C.require("CATALOG")
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=C.PROFILE)
    for key, (service, name, handler) in ours().items():
        if a.service not in (key, "all"):
            continue
        cur = current(w, service)
        print(f"{service}: {[(p.get('name'), p.get('rank')) for p in cur]}")
        if a.action == "status":
            continue
        new = desired(cur, name, handler, a.action == "attach")
        print(f"  {a.action} {name} -> {[(p.get('name'), p.get('rank')) for p in new]}")
        if a.apply:
            w.api_client.do("PATCH", API + service, query={"update_mask": "config.service_policies"},
                            body={"config": {"service_policies": new}})
            after = current(w, service)
            others = lambda ps: sorted(json.dumps(p, sort_keys=True) for p in ps if p.get("name") != name)  # noqa: E731
            if others(after) != others(cur):
                print(f"  WARNING other policies on {service} changed during the update (concurrent edit or fields the "
                      f"API does not return): before {others(cur)} after {others(after)}")
            print(f"  applied: {[(p.get('name'), p.get('rank')) for p in after]}")
        else:
            print("  dry run: add --apply to write")


if __name__ == "__main__":
    main()
