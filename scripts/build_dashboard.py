"""Build and (with --deploy) publish the traceability dashboard for the target: who called which Gateway MCP tool, as whom,
with what outcome, plus a Unity Gateway policies page and an agent/test traffic filter.
Starts from dashboards/governed_tools_trace.lvdash.json (template, unchanged) and writes dashboards/out/<env>.lvdash.json.
Needs the trace objects from `run_setup.py --steps traces` (policy_events + traffic views).
Usage: BEV_TARGET=<target> python scripts/build_dashboard.py [--deploy]
"""
import argparse
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "setup"))
import config as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "dashboards"
SRC = ROOT / "governed_tools_trace.lvdash.json"

ap = argparse.ArgumentParser()
ap.add_argument("--deploy", action="store_true", help="create or update the dashboard in the workspace and publish it")
ap.add_argument("--parent", help="workspace folder (default: your home folder)")
args = ap.parse_args()
C.require("WORKSPACE_ID", "REGIONAL_SP_APP_ID", "USER", "CATALOG", "WAREHOUSE_ID")
a = argparse.Namespace(workspace_id=C.WORKSPACE_ID, sp_app_id=C.REGIONAL_SP_APP_ID, sp_name=C.REGIONAL_SP_NAME,
                       user_email=C.USER, pricing_schema=f"{C.CATALOG}.{C.SCHEMA}",
                       policy_table=f"{C.CATALOG}.{C.TRACE_SCHEMA}.policy_events",
                       traffic_schema=f"{C.CATALOG}.{C.TRACE_SCHEMA}")
OUT = ROOT / "out" / f"{C.ENV}.lvdash.json"

d = json.loads(SRC.read_text())
vals = {"workspace_id": a.workspace_id, "sp_app_id": a.sp_app_id, "sp_display_name": a.sp_name,
        "user_email": a.user_email, "pricing_schema": a.pricing_schema}
for ds in d["datasets"]:
    for p in ds.get("parameters", []):
        if vals.get(p["keyword"]):
            p["defaultSelection"] = {"values": {"dataType": "STRING", "values": [{"value": vals[p["keyword"]]}]}}

# policy decisions dataset (identity mapped like the other datasets)
sp = a.sp_app_id.replace("'", "")
d["datasets"].append({"name": "ds_policy_events", "displayName": "Unity Gateway policy decisions (unified trace table snapshot)",
  "queryLines": [
    "SELECT event_time, request_id,\n",
    f"  CASE WHEN identity = '{sp}' THEN '{a.sp_name} (SP)' ELSE identity END AS identity,\n",
    "  CASE WHEN requester_type = 'SERVICE_PRINCIPAL' THEN 'Service principal' ELSE 'End user (OBO)' END AS identity_type,\n",
    "  left(regexp_replace(sql_text, '\\\\s+', ' '), 160) AS sql_text,\n",
    "  CASE WHEN policy_type <> 'CUSTOM' THEN 'Built-in: block_jailbreak (SQL)'\n",
    "       WHEN mcp_service = 'system.ai.microsoft_365' THEN 'Custom: approved documents only (Microsoft 365)'\n",
    "       ELSE 'Custom: read-only, pricing schema only (SQL)' END AS policy,\n",
    "  concat(replace(mcp_service, 'system.ai.', ''), ' / ', coalesce(tool, 'unknown')) AS tool,\n",
    "  CASE phase WHEN 'on_call' THEN 'Before the call' WHEN 'on_result' THEN 'On the tool result' ELSE phase END AS phase,\n",
    "  decision, reason,\n",
    "  CASE WHEN decision = 'Blocked' THEN 1 ELSE 0 END AS is_blocked,\n",
    "  CASE WHEN decision = 'Detected (log mode)' THEN 1 ELSE 0 END AS is_detected\n",
    f"FROM {a.policy_table}\n"]})

# include the Microsoft 365 MCP in the traceability datasets and subtitle
for ds in d["datasets"]:
    ds["queryLines"] = [x.replace("('system.ai.dbsql', 'system.ai.genie_one_mcp')", "('system.ai.dbsql', 'system.ai.genie_one_mcp', 'system.ai.microsoft_365')") for x in ds["queryLines"]]
for it in d["pages"][0]["layout"]:
    tb = it["widget"].get("multilineTextboxSpec")
    if tb:
        tb["lines"] = [x.replace("(system.ai.dbsql, system.ai.genie_one_mcp)", "(system.ai.dbsql, system.ai.genie_one_mcp, system.ai.microsoft_365)") for x in tb["lines"]]
L = {it["widget"]["name"]: it for it in d["pages"][0]["layout"]}

# denied table shows only agent tool calls (Gateway MCP) stopped by UC permissions, not setup/SQL errors
den = L["tbl_denied"]["widget"]
den["queries"][0]["query"]["filters"] = [{"expression": "`is_denied` = 1"}, {"expression": "`tool` = 'dbsql / execute_sql'"}]
den["spec"]["frame"]["title"] = "Denied by Unity Catalog (agent tool calls)"


def text(name, line, y):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": [line]}}, "position": {"x": 0, "y": y, "width": 12, "height": 1}}


def counter(name, title, desc, expr, x):
    w = copy.deepcopy(L["kpi_denied"])
    w["widget"]["name"] = name
    q = w["widget"]["queries"][0]["query"]
    q["datasetName"], q["fields"] = "ds_policy_events", [{"name": name, "expression": expr}]
    enc = w["widget"]["spec"]["encodings"]["value"]
    enc["fieldName"], enc["displayName"] = name, title
    w["widget"]["spec"]["frame"].update({"title": title, "description": desc})
    w["position"] = {"x": x, "y": 2, "width": 4, "height": 3}
    return w


def table(name, title, desc, cols, y, h, flt=None):
    w = copy.deepcopy(L["tbl_denied"])
    w["widget"]["name"] = name
    q = w["widget"]["queries"][0]["query"]
    q["datasetName"] = "ds_policy_events"
    q["fields"] = [{"name": c, "expression": f"`{c}`"} for c, _ in cols]
    if flt:
        q["filters"] = [{"expression": flt}]
    else:
        q.pop("filters", None)
    w["widget"]["spec"]["encodings"]["columns"] = [{"fieldName": c, "displayName": n} for c, n in cols]
    w["widget"]["spec"]["frame"].update({"title": title, "description": desc})
    w["position"] = {"x": 0, "y": y, "width": 12, "height": h}
    return w


cols = [("event_time", "Time"), ("identity", "Identity"), ("decision", "Decision"), ("policy", "Policy"), ("phase", "When"),
        ("tool", "Tool"), ("reason", "Reason"), ("sql_text", "Request sent by the agent (SQL or document)")]
page = {"name": "policies", "displayName": "Gateway policies", "pageType": "PAGE_TYPE_CANVAS", "layout": [
    text("h_pol", "### Unity Gateway policies on SQL and Microsoft 365 tools — what was blocked or detected, and why", 0),
    text("h_pol_sub", "Custom policies run before the call (deterministic): SQL is read-only on the pricing schema; Microsoft 365 is limited to one approved document folder. The jailbreak judge screens SQL tool results for indirect prompt injection (log mode here).", 1),
    counter("kpi_blocked", "Blocked by policy", "Custom policy, before the call", "SUM(`is_blocked`)", 0),
    counter("kpi_detected", "Injection detected", "Jailbreak judge on tool results", "SUM(`is_detected`)", 4),
    counter("kpi_evaluated", "Policy evaluations", "All policy checks recorded", "COUNT(`request_id`)", 8),
    table("tbl_pol_flagged", "Blocked and detected", "Each row is one policy decision with the reason the Gateway recorded", cols, 5, 6,
          "`decision` <> 'Allowed'"),
    table("tbl_pol_all", "All policy evaluations", "Allowed calls show the same checks passing", cols, 11, 8)]}
d["pages"].insert(1, page)

# traffic filter: agents vs test traffic (rule lives in the views)
if a.traffic_schema:
    T = a.traffic_schema
    TEST = "Test (scripts, CLI, playground)"
    VIEWS = ["Agents (governed + unguarded)", "Governed agent only", "Unguarded agent only", "Test only", "All traffic"]
    cls = f"coalesce(t.traffic_class, '{TEST}')"
    pred = (f"  AND (:traffic_view = 'All traffic'\n"
            f"    OR (:traffic_view = 'Agents (governed + unguarded)' AND {cls} <> '{TEST}')\n"
            f"    OR (:traffic_view = 'Governed agent only' AND {cls} = 'Governed agent')\n"
            f"    OR (:traffic_view = 'Unguarded agent only' AND {cls} = 'Unguarded agent')\n"
            f"    OR (:traffic_view = 'Test only' AND {cls} = '{TEST}'))\n")
    calls = f"LEFT JOIN (SELECT request_id, traffic_class FROM {T}.mcp_call_traffic) t ON t.request_id = "
    join = {"ds_tool_calls": ("FROM system.ai_gateway.usage u\n", calls + "u.request_id\n", "u.event_time,\n"),
            "ds_statements": ("FROM system.query.history q\n", f"LEFT JOIN {T}.statement_traffic t ON t.statement_id = q.statement_id\n", "q.start_time,\n"),
            "ds_audit": ("FROM system.access.audit a\n", calls + "a.request_id\n", "a.event_time,\n"),
            "ds_policy_events": (f"FROM {a.policy_table}\n", calls + "p.request_id\n", "SELECT p.event_time, p.request_id,\n")}
    param = {"displayName": "traffic_view", "keyword": "traffic_view", "dataType": "STRING",
             "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": VIEWS[0]}]}}}
    for ds in d["datasets"]:
        if ds["name"] not in join:
            continue
        frm, j, first = join[ds["name"]]
        q = "".join(ds["queryLines"])
        if ds["name"] == "ds_policy_events":
            q = q.replace("SELECT event_time, request_id,", "SELECT p.event_time, p.request_id,").replace(frm, f"FROM {a.policy_table} p\n" + j + "WHERE true\n" + pred)
        else:
            q = q.replace(frm, frm + j, 1)
            q = q.replace("\nORDER BY", "\n" + pred.rstrip("\n") + "\nORDER BY", 1) if "\nORDER BY" in q else q.rstrip("\n") + "\n" + pred
        q = q.replace(first, first + f"  {cls} AS traffic_class,\n", 1)
        ds["queryLines"] = [x + "\n" for x in q.rstrip("\n").split("\n")]
        ds.setdefault("parameters", []).append(copy.deepcopy(param))
    d["datasets"].append({"name": "ds_traffic_views", "displayName": "Traffic filter options",
                          "queryLines": ["SELECT v AS traffic_view, i AS sort_order\n",
                                         "FROM (SELECT posexplode(array(" + ", ".join(f"'{v}'" for v in VIEWS) + ")) AS (i, v))\n"]})
    mix = next(x for x in d["datasets"] if x["name"] == "ds_tool_calls")
    d["datasets"].append({"name": "ds_traffic_mix", "displayName": "Traffic mix (all classes, not filtered by traffic)",
                          "queryLines": ["".join(mix["queryLines"]).split("  AND (:traffic_view")[0] + "\n"],
                          "parameters": [copy.deepcopy(p) for p in mix["parameters"] if p["keyword"] != "traffic_view"]})
    ds_names = [x for x in join]
    gf = next(p for p in d["pages"] if p["name"] == "global_filters")
    fw = gf["layout"][0]["widget"]
    fw["queries"].append({"name": "q_ds_traffic_mix", "query": {"datasetName": "ds_traffic_mix", "parameters": [{"name": "date_range", "keyword": "date_range"}], "disaggregated": False}})
    fw["spec"]["encodings"]["fields"].append({"parameterName": "date_range", "queryName": "q_ds_traffic_mix"})
    tq = [{"name": "q_opts", "query": {"datasetName": "ds_traffic_views", "fields": [
        {"name": "traffic_view", "expression": "`traffic_view`"},
        {"name": "traffic_view_associativity", "expression": "COUNT_IF(`associative_filter_predicate_group`)"}], "disaggregated": False}}]
    tq += [{"name": f"q_{n}_tv", "query": {"datasetName": n, "parameters": [{"name": "traffic_view", "keyword": "traffic_view"}], "disaggregated": False}} for n in ds_names]
    gf["layout"].append({"widget": {"name": "f_traffic_view", "queries": tq, "spec": {
        "version": 2, "widgetType": "filter-single-select",
        "encodings": {"fields": [{"fieldName": "traffic_view", "displayName": "Traffic", "queryName": "q_opts"}] +
                      [{"parameterName": "traffic_view", "queryName": f"q_{n}_tv"} for n in ds_names]},
        "selection": {"defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": VIEWS[0]}]}}},
        "frame": {"showTitle": True, "title": "Traffic (default: agents only)"}}},
        "position": {"x": 4, "y": 0, "width": 4, "height": 2}})
    tp = d["pages"][0]["layout"]
    for it in tp:
        if it["position"]["y"] >= 6:
            it["position"]["y"] += 6
    w = copy.deepcopy(next(it for it in tp if it["widget"]["name"] == "bar_identity_tool"))
    w["widget"]["name"] = "bar_traffic_mix"
    q = w["widget"]["queries"][0]["query"]
    q["datasetName"] = "ds_traffic_mix"
    q["fields"] = [{"name": "traffic_class", "expression": "`traffic_class`"}, {"name": "mcp_service", "expression": "`mcp_service`"},
                   {"name": "count(event_time)", "expression": "COUNT(`event_time`)"}]
    enc = w["widget"]["spec"]["encodings"]
    enc["x"].update({"fieldName": "traffic_class", "displayName": "Traffic"})
    enc["color"].update({"fieldName": "mcp_service", "displayName": "MCP service"})
    w["widget"]["spec"]["frame"].update({"title": "Traffic mix: agents vs test traffic",
        "description": "All Gateway tool calls in the date range, whatever the Traffic filter. Foundry agents = no user agent; scripts/CLI/playgrounds = test"})
    w["position"] = {"x": 0, "y": 6, "width": 12, "height": 6}
    tp.append(w)
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
print(f"wrote dashboards/out/{OUT.name}: pages {[p['displayName'] for p in d['pages']]}")

if args.deploy:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.dashboards import Dashboard
    w = WorkspaceClient(profile=C.PROFILE)
    parent = args.parent or f"/Users/{w.current_user.me().user_name}"
    name = f"Governed agent tools ({C.ENV}) - who asked what + Gateway policies"
    body = Dashboard(display_name=name, parent_path=parent, warehouse_id=C.WAREHOUSE_ID, serialized_dashboard=json.dumps(d))
    found = [x for x in w.lakeview.list() if x.display_name == name and (x.path or "").startswith(parent)]
    dash = w.lakeview.update(found[0].dashboard_id, body) if found else w.lakeview.create(body)
    # embed_credentials=False: every viewer queries system tables with their own permissions
    w.lakeview.publish(dash.dashboard_id, warehouse_id=C.WAREHOUSE_ID, embed_credentials=False)
    C.save_resolved(BEV_DASHBOARD_ID=dash.dashboard_id)
    print(f"published: {C.HOST or ''}/dashboardsv3/{dash.dashboard_id}/published")
