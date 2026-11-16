"""Create a new Foundry prompt-agent version from infra/foundry/agent.yaml (idempotent).

Usage: BEV_TARGET=<target> python infra/foundry/agent.py [--agent infra/foundry/agent.yaml]
           [--steps connection,toolbox,agent] [--dry-run] [--force]
agent*.yaml are templates: ${catalog}, ${schema}, SharePoint ids, connection and toolbox names come from the target.
Steps: connection = ARM GET of the MCP project connection (read-only; created manually in the UI).
       toolbox    = ensure toolbox version exists and its MCP tool points at the connection (creates it only if missing).
       agent      = POST a new agent version when the latest one differs from agent.yaml, then smoke-check it.
Tokens come from `az account get-access-token`; nothing secret is printed.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

from _common import load_cfg, project_endpoint, render_agent

ARM_API = "2025-06-01"
DATA_API = "v1"


def sh(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"FAILED: {' '.join(args[:3])}...\n{r.stderr[-600:]}")
    return r.stdout.strip()


def token(resource, tenant):
    return sh("az", "account", "get-access-token", "--resource", resource, "--tenant", tenant,
              "--query", "accessToken", "-o", "tsv")


def call(method, url, tok, body=None, allow=()):
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code in allow:
            return None
        sys.exit(f"{method} {url.split('?')[0]} -> {e.code}: {e.read()[:300]!r}")


def arm_connection_url(cfg, name):
    return (f"https://management.azure.com/subscriptions/{cfg['subscription_id']}/resourceGroups/{cfg['resource_group']}"
            f"/providers/Microsoft.CognitiveServices/accounts/{cfg['foundry_account']}"
            f"/projects/{cfg['foundry_project']}/connections/{name}?api-version={ARM_API}")


def mcp_tools(agent):
    return [t for t in agent.get("tools", []) if t["type"] == "mcp"]


def mcp_server_url(ep, toolbox, version):
    return f"{ep}/toolboxes/{toolbox}/versions/{version}/mcp?api-version={DATA_API}"


def step_connection(cfg, agent, arm):
    for t in mcp_tools(agent):
        c = call("GET", arm_connection_url(cfg, t["connection"]), arm)
        p = c["properties"]
        if p.get("authType") != "OAuth2" or p.get("category") != "RemoteTool":
            sys.exit(f"connection {t['connection']}: expected RemoteTool/OAuth2, got {p.get('category')}/{p.get('authType')}")
        print(f"connection {t['connection']}: RemoteTool OAuth2 -> host {urlparse(p['target']).netloc}")
    return {t["connection"]: c["properties"]["target"] for t in mcp_tools(agent)}


def step_toolbox(cfg, agent, data, targets):
    ep = project_endpoint(cfg)
    for t in mcp_tools(agent):
        tb, ver, conn = t["toolbox"], t["toolbox_version"], t["connection"]
        got = call("GET", f"{ep}/toolboxes/{tb}/versions/{ver}?api-version={DATA_API}", data, allow=(404,))
        if got is None:
            body = {"description": t.get("description") or agent.get("description", ""),
                    "tools": [{"type": "mcp", "server_label": t["server_label"], "project_connection_id": conn,
                               "server_url": targets[conn]}] + list(t.get("extra_tools", []))}
            got = call("POST", f"{ep}/toolboxes/{tb}/versions?api-version={DATA_API}", data, body)
            print(f"toolbox {tb}: created version {got.get('version')}")
        mcp = [x for x in got.get("tools", []) if x.get("type") == "mcp"]
        if not any(x.get("project_connection_id") == conn for x in mcp):
            sys.exit(f"toolbox {tb} v{ver}: no MCP tool bound to connection {conn}")
        print(f"toolbox {tb} v{ver}: MCP tool -> connection {conn} OK")
        allowed = {x["type"] for x in t.get("extra_tools", [])}
        extra = sorted({x.get("type") for x in got.get("tools", []) if x.get("type") not in {"mcp"} | allowed})
        if extra:
            print(f"WARNING toolbox {tb} v{ver} also exposes {extra}; agent instructions allow execute_sql only. "
                  "Publish a toolbox version without them and bump toolbox_version in agent.yaml.")


def desired_definition(cfg, agent):
    ep = project_endpoint(cfg)
    tools = []
    for t in agent.get("tools", []):
        if t["type"] != "mcp":
            sys.exit(f"unsupported tool type in agent.yaml: {t['type']}")
        tools.append({"type": "mcp", "server_label": t["server_label"],
                      "server_url": mcp_server_url(ep, t["toolbox"], t["toolbox_version"]),
                      "require_approval": t.get("require_approval", "never")})
    return {"kind": agent["kind"], "model": agent["model"], "instructions": agent["instructions"],
            "reasoning": agent.get("reasoning") or {}, "tools": tools}


def norm_def(d):
    tools = []
    for t in d.get("tools", []):
        ra = t.get("require_approval")
        if isinstance(ra, dict):  # compare dict policies structurally
            ra = json.dumps(ra, sort_keys=True)
        tools.append({"type": t.get("type"), "server_label": t.get("server_label"),
                      "server_url": t.get("server_url"), "require_approval": ra})
    return {"kind": d.get("kind"), "model": d.get("model"), "instructions": (d.get("instructions") or "").strip(),
            "reasoning": d.get("reasoning") or {}, "tools": tools}


def step_agent(cfg, agent, data, dry_run, force):
    ep = project_endpoint(cfg)
    name = agent["name"]
    want = desired_definition(cfg, agent)
    if dry_run:
        print(json.dumps({"definition": want}, indent=2))
        return
    cur = call("GET", f"{ep}/agents/{name}?api-version={DATA_API}", data, allow=(404,))
    latest = (cur or {}).get("versions", {}).get("latest")
    if latest and not force and norm_def(latest["definition"]) == norm_def(want):
        print(f"agent {name}: latest v{latest['version']} already matches agent.yaml; nothing to do")
        return latest["version"]
    body = {"definition": want, "description": agent.get("description", "")}
    created = call("POST", f"{ep}/agents/{name}/versions?api-version={DATA_API}", data, body)
    ver = created["version"]
    print(f"agent {name}: created version {ver} (id {created['id']})")
    smoke(cfg, name, ver, data, want)
    return ver


def smoke(cfg, name, ver, data, want):
    # read-only check: the version exists and carries the MCP tool with the expected URL
    got = call("GET", f"{project_endpoint(cfg)}/agents/{name}/versions/{ver}?api-version={DATA_API}", data)
    tools = got["definition"].get("tools", [])
    ok = [t for t in tools if t.get("type") == "mcp" and t.get("server_url") == want["tools"][0]["server_url"]]
    if not ok:
        sys.exit(f"smoke: v{ver} has no MCP tool with the expected server_url")
    print(f"smoke: v{ver} status={got.get('status')} draft={got.get('draft')} mcp_tools={len(ok)} OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="default targets/<BEV_TARGET>.foundry.yml")
    ap.add_argument("--agent", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.yaml"))
    ap.add_argument("--steps", default="connection,toolbox,agent")
    ap.add_argument("--dry-run", action="store_true", help="print the definition that would be posted")
    ap.add_argument("--force", action="store_true", help="create a version even if the latest matches")
    args = ap.parse_args()
    cfg = load_cfg(args.config)
    agent = render_agent(args.agent, cfg)
    steps = args.steps.split(",")
    data = token(cfg["ai_audience"], cfg["tenant_id"])
    arm = token("https://management.azure.com/", cfg["tenant_id"])
    targets = step_connection(cfg, agent, arm) if "connection" in steps else {
        t["connection"]: call("GET", arm_connection_url(cfg, t["connection"]), arm)["properties"]["target"]
        for t in mcp_tools(agent)}
    if "toolbox" in steps and not args.dry_run:
        step_toolbox(cfg, agent, data, targets)
    if "agent" in steps:
        step_agent(cfg, agent, data, args.dry_run, args.force)


if __name__ == "__main__":
    main()
