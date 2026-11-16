"""Provision the Foundry front door + Entra identities for the governed-tools example (idempotent).

Usage: BEV_TARGET=<target> python infra/foundry/provision.py [--steps entra,databricks,foundry,rbac] [--rotate]
Config: targets/<target>.foundry.yml (Azure side) + targets/<target>.env (names, tenant, Databricks profile).
Requires: az CLI logged in to the tenant + subscription; databricks CLI profile for the workspace.
Secrets go straight into a Databricks secret scope and are never printed. App ids are saved to targets/<target>.resolved.env.
"""
import argparse
import json
import subprocess
import sys
import urllib.request

from _common import C, load_cfg

ADB_RESOURCE_APP = C.ADB_RESOURCE_APP
ARM_API = "2025-06-01"


def sh(*args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"FAILED: {' '.join(args[:4])}...\n{r.stderr[-800:]}")
    return r.stdout.strip()


def token(resource_args, tenant):
    return sh("az", "account", "get-access-token", *resource_args, "--tenant", tenant, "--query", "accessToken", "-o", "tsv")


def http(method, url, tok, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {url} -> {e.code}: {e.read()[:600]}")


def tag_strings(tags):
    return [f"{k}:{v}" for k, v in tags.items()]


# --- Entra: app + SP, idempotent by displayName ---
def ensure_app(g, name, tags, required_access=None):
    q = http("GET", f"https://graph.microsoft.com/v1.0/applications?$filter=displayName eq '{name}'".replace(" ", "%20"), g)["value"]
    body = {"displayName": name, "signInAudience": "AzureADMyOrg", "tags": tag_strings(tags),
            "notes": "; ".join(f"{k}={v}" for k, v in tags.items())}
    if required_access:
        body["requiredResourceAccess"] = required_access
    if q:
        app = q[0]
        http("PATCH", f"https://graph.microsoft.com/v1.0/applications/{app['id']}", g, body)
    else:
        app = http("POST", "https://graph.microsoft.com/v1.0/applications", g, body)
    sps = http("GET", f"https://graph.microsoft.com/v1.0/servicePrincipals?$filter=appId eq '{app['appId']}'".replace(" ", "%20"), g)["value"]
    sp = sps[0] if sps else http("POST", "https://graph.microsoft.com/v1.0/servicePrincipals", g, {"appId": app["appId"]})
    http("PATCH", f"https://graph.microsoft.com/v1.0/servicePrincipals/{sp['id']}", g, {"tags": tag_strings(tags)})
    print(f"entra app {name}: appId={app['appId']} app_obj={app['id']} sp_obj={sp['id']}")
    return app, sp


def workspace(cfg):
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(profile=cfg["databricks_profile"])


def put_secret(cfg, key, value):
    # through the SDK (request body), never on a command line where the process list would show it
    workspace(cfg).secrets.put_secret(cfg["secret_scope"], key, string_value=value)


def ensure_secret(g, cfg, app, label, key, rotate):
    existing = [p for p in app.get("passwordCredentials", []) if p.get("displayName") == label]
    if existing and not rotate:
        print(f"secret {label}: exists (use --rotate to replace)")
        return
    sec = http("POST", f"https://graph.microsoft.com/v1.0/applications/{app['id']}/addPassword", g,
               {"passwordCredential": {"displayName": label, "endDateTime": cfg["secret_expiry"]}})["secretText"]
    put_secret(cfg, key, sec)
    # rotation: the old credentials stop working once the new one is stored
    for p in existing:
        http("POST", f"https://graph.microsoft.com/v1.0/applications/{app['id']}/removePassword", g, {"keyId": p["keyId"]})
    print(f"secret {label}: stored in scope {cfg['secret_scope']}/{key}" + (f", {len(existing)} old credential(s) removed" if existing else ""))


def step_entra(cfg, rotate):
    g = token(["--resource-type", "ms-graph"], cfg["tenant_id"])
    adb = http("GET", f"https://graph.microsoft.com/v1.0/servicePrincipals?$filter=appId eq '{ADB_RESOURCE_APP}'".replace(" ", "%20"), g)["value"][0]
    scope_id = next(s["id"] for s in adb["oauth2PermissionScopes"] if s["value"] == "user_impersonation")
    w = workspace(cfg)
    if cfg["secret_scope"] not in {x.name for x in w.secrets.list_scopes()}:
        w.secrets.create_scope(cfg["secret_scope"])

    reg, _ = ensure_app(g, cfg["regional_sp_name"], cfg["tags"])
    ensure_secret(g, cfg, reg, "regional-sp", "regional-sp-client-secret", rotate)
    put_secret(cfg, "regional-sp-client-id", reg["appId"])

    access = [{"resourceAppId": ADB_RESOURCE_APP, "resourceAccess": [{"id": scope_id, "type": "Scope"}]}]
    pt, _ = ensure_app(g, cfg["passthrough_app_name"], cfg["tags"], access)
    if cfg.get("passthrough_redirect_uris"):
        http("PATCH", f"https://graph.microsoft.com/v1.0/applications/{pt['id']}", g,
             {"web": {"redirectUris": cfg["passthrough_redirect_uris"]}})
        print(f"redirect URIs set: {cfg['passthrough_redirect_uris']}")
    ensure_secret(g, cfg, pt, "foundry-passthrough", "foundry-passthrough-client-secret", rotate)
    C.save_resolved(BEV_REGIONAL_SP_APP_ID=reg["appId"], BEV_PASSTHROUGH_APP_ID=pt["appId"])
    return reg["appId"]


# --- Databricks: add the Entra SP to the workspace ---
def step_databricks(cfg, regional_app_id=None):
    p = cfg["databricks_profile"]
    if not regional_app_id:
        regional_app_id = sh("databricks", "secrets", "get-secret", cfg["secret_scope"], "regional-sp-client-id", "-p", p, "-o", "json")
        regional_app_id = __import__("base64").b64decode(json.loads(regional_app_id)["value"]).decode()
    existing = json.loads(sh("databricks", "service-principals", "list", "--filter", f"applicationId eq {regional_app_id}", "-p", p, "-o", "json") or "[]")
    # Databricks SQL access only: the persona queries through the Gateway dbsql MCP, nothing else
    ent = [{"value": "databricks-sql-access"}]
    if existing:
        sp_id = existing[0]["id"]
        sh("databricks", "service-principals", "patch", sp_id, "--json", json.dumps({
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "entitlements", "value": ent}]}), "-p", p)
        print(f"workspace SP exists: id={sp_id} (entitlement databricks-sql-access ensured)")
        return
    out = json.loads(sh("databricks", "service-principals", "create", "--json",
                        json.dumps({"applicationId": regional_app_id, "displayName": cfg["regional_sp_name"], "active": True,
                                    "entitlements": ent}), "-p", p, "-o", "json"))
    print(f"workspace SP created: id={out['id']} (entitlement databricks-sql-access)")


# --- Foundry: account + project + model deployment (ARM) ---
def step_foundry(cfg):
    a = token(["--resource", "https://management.azure.com/"], cfg["tenant_id"])
    base = (f"https://management.azure.com/subscriptions/{cfg['subscription_id']}/resourceGroups/{cfg['resource_group']}"
            f"/providers/Microsoft.CognitiveServices/accounts/{cfg['foundry_account']}")
    http("PUT", f"{base}?api-version={ARM_API}", a, {
        "location": cfg["location"], "kind": "AIServices", "sku": {"name": "S0"}, "identity": {"type": "SystemAssigned"},
        "tags": cfg["tags"], "properties": {"customSubDomainName": cfg["foundry_account"], "allowProjectManagement": True,
                                            "publicNetworkAccess": cfg.get("public_network_access", "Enabled"), "disableLocalAuth": True}})
    import time
    for _ in range(40):
        if http("GET", f"{base}?api-version={ARM_API}", a)["properties"]["provisioningState"] == "Succeeded":
            break
        time.sleep(15)
    proj = http("PUT", f"{base}/projects/{cfg['foundry_project']}?api-version={ARM_API}", a, {
        "location": cfg["location"], "identity": {"type": "SystemAssigned"}, "tags": cfg["tags"],
        "properties": {"displayName": cfg["foundry_project"], "description": cfg.get("project_description", "")}})
    m = cfg["model"]
    http("PUT", f"{base}/deployments/{m['deployment']}?api-version={ARM_API}", a, {
        "sku": {"name": m.get("sku", "GlobalStandard"), "capacity": m.get("capacity", 100)}, "tags": cfg["tags"],
        "properties": {"model": {"format": "OpenAI", "name": m["name"], **({"version": m["version"]} if m.get("version") else {})}}})
    print(f"foundry: account={cfg['foundry_account']} project={cfg['foundry_project']} model={m['deployment']}")
    print(f"project endpoint: {proj.get('properties', {}).get('endpoints', {})}")


# --- RBAC: data-plane role for the users (run by a principal allowed to assign roles) ---
def step_rbac(cfg):
    scope = (f"/subscriptions/{cfg['subscription_id']}/resourceGroups/{cfg['resource_group']}"
             f"/providers/Microsoft.CognitiveServices/accounts/{cfg['foundry_account']}")
    for oid in cfg.get("foundry_user_object_ids", []):
        r = subprocess.run(["az", "role", "assignment", "create", "--assignee-object-id", oid, "--assignee-principal-type", "User",
                            "--role", cfg.get("foundry_user_role", "Foundry User"), "--scope", scope,
                            "--subscription", cfg["subscription_id"], "-o", "none"], capture_output=True, text=True)
        print(f"rbac {oid}: {'ok' if r.returncode == 0 else r.stderr.strip()[-300:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="default targets/<BEV_TARGET>.foundry.yml")
    ap.add_argument("--steps", default="entra,databricks,foundry,rbac")
    ap.add_argument("--rotate", action="store_true", help="add new client secrets even if they exist")
    args = ap.parse_args()
    cfg = load_cfg(args.config)
    steps = args.steps.split(",")
    app_id = step_entra(cfg, args.rotate) if "entra" in steps else None
    if "databricks" in steps:
        step_databricks(cfg, app_id)
    if "foundry" in steps:
        step_foundry(cfg)
    if "rbac" in steps:
        step_rbac(cfg)


if __name__ == "__main__":
    main()
