"""Remove everything this environment created, in a safe order. Default = dry run; --apply deletes.

Order matters: policies are detached FIRST. Dropping the schema that holds a policy function while the policy is still
attached leaves the metastore-wide system.ai.* service failing closed for every caller.
Usage: BEV_TARGET=<target> python scripts/teardown.py [--steps policies,foundry_agents,databricks,identities,entra,foundry_account] [--apply]
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "infra", "foundry"))
from _common import C, load_cfg, project_endpoint  # noqa: E402

STEPS = ["policies", "foundry_agents", "databricks", "identities", "entra", "foundry_account"]


def az_token(resource, tenant):
    return subprocess.check_output(["az", "account", "get-access-token", "--resource", resource, "--tenant", tenant,
                                    "--query", "accessToken", "-o", "tsv"], text=True).strip()


def http(method, url, tok):
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {tok}"})
    try:
        urllib.request.urlopen(req, timeout=120).read()
        return "ok"
    except urllib.error.HTTPError as e:
        return "not found" if e.code == 404 else f"HTTP {e.code}: {e.read()[:200]!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default=",".join(STEPS))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    steps, do = a.steps.split(","), a.apply
    C.require("CATALOG")
    print(f"teardown {'APPLY' if do else 'DRY RUN'} env={C.ENV}: {steps}")

    if "policies" in steps:
        cmd = [sys.executable, os.path.join(ROOT, "setup", "policies.py"), "detach"] + (["--apply"] if do else [])
        subprocess.run(cmd, check=True)

    cfg = load_cfg() if {"foundry_agents", "entra", "foundry_account"} & set(steps) else None
    if "foundry_agents" in steps:
        ep, tok = project_endpoint(cfg), az_token(cfg["ai_audience"], cfg["tenant_id"])
        for kind, name in [("agents", C.AGENT_GOVERNED), ("agents", C.AGENT_NAIVE),
                           ("toolboxes", cfg["sql_toolbox"]), ("toolboxes", cfg["m365_toolbox"])]:
            print(f"-> delete Foundry {kind[:-1]} {name}")
            if do:
                print("  ", http("DELETE", f"{ep}/{kind}/{name}?api-version=v1", tok))
        print("   MCP connections: delete them in the Foundry portal (or delete the whole account with the foundry_account step)")

    if "databricks" in steps:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient(profile=C.PROFILE)
        # dropping the schema of an attached policy function blocks the shared system.ai.* service for every caller
        sys.path.insert(0, os.path.join(ROOT, "setup"))
        import policies as P
        attached = [(svc, n) for svc, n, _ in P.ours().values() if any(p.get("name") == n for p in P.current(w, svc))]
        if attached:
            sys.exit(f"policies still attached {attached}: run the policies step first (./teardown.sh runs it)")
        if C.WAREHOUSE_ID:
            for s in (C.SCHEMA, C.TRACE_SCHEMA):
                print(f"-> DROP SCHEMA {C.CATALOG}.{s} CASCADE")
                if do:
                    w.statement_execution.execute_statement(warehouse_id=C.WAREHOUSE_ID, wait_timeout="50s",
                                                            statement=f"DROP SCHEMA IF EXISTS {C.CATALOG}.{s} CASCADE")
        else:
            print("   no warehouse id: drop the schemas by hand")
        if os.environ.get("BEV_DASHBOARD_ID"):
            print(f"-> trash dashboard {os.environ['BEV_DASHBOARD_ID']}")
            if do:
                w.lakeview.trash(os.environ["BEV_DASHBOARD_ID"])
        if C.WAREHOUSE_ID:
            print(f"-> delete warehouse {C.WAREHOUSE_NAME} ({C.WAREHOUSE_ID})")
            if do:
                w.warehouses.delete(C.WAREHOUSE_ID)
        print(f"-> delete secret scope {C.SECRET_SCOPE}")
        if do:
            try:
                w.secrets.delete_scope(C.SECRET_SCOPE)
            except Exception as e:  # already gone
                print("  ", type(e).__name__, str(e)[:120])
        for sp in (w.service_principals.list(filter=f'applicationId eq "{C.REGIONAL_SP_APP_ID}"') if C.REGIONAL_SP_APP_ID else []):
            print(f"-> delete workspace SP {sp.display_name} ({sp.id})")
            if do:
                w.service_principals.delete(sp.id)

    if "identities" in steps and C.ACCOUNT_PROFILE:
        from databricks.sdk import AccountClient
        acct = AccountClient(profile=C.ACCOUNT_PROFILE)
        # only groups whose members are this environment's identities (the names alone could belong to someone else)
        ours = {u.id for u in acct.users.list(filter=f'userName eq "{C.USER}"')} if C.USER else set()
        if C.REGIONAL_SP_APP_ID:
            ours |= {sp.id for sp in acct.service_principals.list(filter=f'applicationId eq "{C.REGIONAL_SP_APP_ID}"')}
        for g in (C.GROUP_ADMIN, C.GROUP_EAST, C.GROUP_WEST):
            for grp in acct.groups.list(filter=f'displayName eq "{g}"'):
                if grp.display_name != g:
                    continue
                others = {m.value for m in (acct.groups.get(grp.id).members or [])} - ours
                if others:
                    print(f"   SKIP account group {g} ({grp.id}): it has {len(others)} member(s) outside this environment")
                    continue
                print(f"-> delete account group {g} ({grp.id})")
                if do:
                    acct.groups.delete(grp.id)

    if "entra" in steps:
        g = az_token("https://graph.microsoft.com", cfg["tenant_id"])
        for name in (cfg["regional_sp_name"], cfg["passthrough_app_name"]):
            url = f"https://graph.microsoft.com/v1.0/applications?$filter=displayName eq '{name}'".replace(" ", "%20")
            apps = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {g}"})).read())["value"]
            want = {f"{k}:{v}" for k, v in cfg["tags"].items()}
            for app in apps:
                # provision.py tags every app it creates; an untagged same-name app is not ours
                if app.get("displayName") != name or not want <= set(app.get("tags") or []):
                    print(f"   SKIP Entra app {name} ({app['appId']}): not tagged by this environment")
                    continue
                print(f"-> delete Entra app {name} ({app['appId']})")
                if do:
                    print("  ", http("DELETE", f"https://graph.microsoft.com/v1.0/applications/{app['id']}", g))

    if "foundry_account" in steps:
        arm = az_token("https://management.azure.com/", cfg["tenant_id"])
        url = (f"https://management.azure.com/subscriptions/{cfg['subscription_id']}/resourceGroups/{cfg['resource_group']}"
               f"/providers/Microsoft.CognitiveServices/accounts/{cfg['foundry_account']}?api-version=2025-06-01")
        print(f"-> delete Foundry account {cfg['foundry_account']} (project, model, connections, agents)")
        if do:
            print("  ", http("DELETE", url, arm))
            print("   the account is soft-deleted: purge it to reuse the name (az cognitiveservices account purge)")
    if not do:
        print("\ndry run: add --apply to delete")


if __name__ == "__main__":
    main()
