"""Databricks side, step by step: warehouse, schema, tables, load, views, functions, row filters, grants,
tags, smoke test, Gateway policy functions and trace views.
Default = dry run (prints every statement, touches nothing). --apply executes on the target.
Usage: BEV_TARGET=<target> python setup/run_setup.py --steps data [--apply]
Step groups: data, grants, policies, traces, scene_plant, scene_reset (or a comma list of single steps, see --help).
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402
from sqlrun import statements  # noqa: E402

DATA = os.path.join(C.ROOT, "data", "out")
SQL = {"schema": "00_schema.sql", "tables": "10_tables.sql", "views": "20_views.sql", "functions": "30_functions.sql",
       "charts": "35_charts.sql", "catalog": "36_describe_tools.sql", "row_filters": "40_row_filters.sql",
       "grants": "50_grants.sql", "test": "60_test_functions.sql", "policy_sql": "70_service_policy.sql",
       "policy_m365": "71_m365_policy.sql", "scene_plant": "80_injection_scene.sql", "scene_reset": "81_injection_reset.sql",
       "policy_events": "90_policy_events_snapshot.sql", "traffic_views": "95_traffic_class_views.sql"}
GROUPS = {"data": ["warehouse", "schema", "tables", "load", "views", "functions", "charts", "catalog", "row_filters", "tags", "test"],
          "grants": ["grants"], "policies": ["policy_sql", "policy_m365"], "traces": ["policy_events", "traffic_views"],
          "scene_plant": ["scene_plant"], "scene_reset": ["scene_reset"]}
STEPS = [s for g in GROUPS.values() for s in g]
LOADED = ["dim_market", "dim_product", "price_observations", "competitor_prices", "competitor_pairs", "promo_events",
          "elasticity_estimates", "sku_pnl", "margin_guardrail_thresholds", "playbook_section", "playbook_question"]
TAGGED = LOADED + ["playbook_answer", "user_market_access", "v_price_position", "pricing_kpis"]


def args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute (default: print the rendered SQL)")
    ap.add_argument("--steps", required=True, help=f"groups {list(GROUPS)} or single steps {STEPS}, comma separated")
    a = ap.parse_args()
    steps = []
    for s in a.steps.split(","):
        steps += GROUPS.get(s, [s])
    bad = [s for s in steps if s not in STEPS]
    if bad:
        ap.error(f"unknown steps {bad}")
    a.steps = steps
    C.require("CATALOG")
    for k in ("CATALOG", "SCHEMA", "TRACE_SCHEMA", "VOLUME"):
        if not re.fullmatch(r"[A-Za-z0-9_]+", getattr(C, k)):
            ap.error(f"{k} must be a plain identifier")
    for k in ("GROUP_ADMIN", "GROUP_EAST", "GROUP_WEST", "USER"):
        if any(ch in getattr(C, k) for ch in "`'\\"):
            ap.error(f"{k} must not contain quotes, backticks or backslashes")
    return a


ID_RE = r"(b!)?[A-Za-z0-9][A-Za-z0-9_-]{7,}"          # Graph item / drive ids, Entra app ids
EMAIL_RE = r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}"
FOLDER_RE = r"[A-Za-z0-9][A-Za-z0-9 _.-]*(/[A-Za-z0-9][A-Za-z0-9 _.-]*)*"


def _check(name, value, pattern):
    if not re.fullmatch(pattern, value) or ".." in value:
        raise SystemExit(f"{name} has unexpected characters or format: {value!r}")
    return value


def policy_params():
    C.require("USER", "PASSTHROUGH_APP_ID", "REGIONAL_SP_APP_ID", "M365_FOLDER", "M365_DRIVE_ID",
              "M365_POLICY_DOC_ID", "M365_GUARDRAILS_ID")
    vals = {"agent_client_id": _check("BEV_PASSTHROUGH_APP_ID", C.PASSTHROUGH_APP_ID, ID_RE),
            "agent_sp_app_id": _check("BEV_REGIONAL_SP_APP_ID", C.REGIONAL_SP_APP_ID, ID_RE),
            "user_email": _check("BEV_USER", C.USER.lower(), EMAIL_RE),
            "folder_path": _check("BEV_M365_FOLDER", C.M365_FOLDER, FOLDER_RE),
            "drive_id": _check("BEV_M365_DRIVE_ID", C.M365_DRIVE_ID, ID_RE),
            "policy_doc_id": _check("BEV_M365_POLICY_DOC_ID", C.M365_POLICY_DOC_ID, ID_RE),
            "guardrails_xlsx_id": _check("BEV_M365_GUARDRAILS_ID", C.M365_GUARDRAILS_ID, ID_RE)}
    # the draft document (optional injection scene) is allowed only when deployed: no id, no clause
    vals["draft_clause"] = ""
    if C.M365_DRAFT_DOC_ID:
        draft = _check("BEV_M365_DRAFT_DOC_ID", C.M365_DRAFT_DOC_ID, ID_RE)
        vals["draft_clause"] = ("\n      OR CAST(COALESCE(event:context.tool.arguments.resource_uri, '') AS STRING) = "
                                f"'/v1.0/drives/{vals['drive_id']}/items/{draft}/content'")
    return vals


def trace_params():
    C.require("TRACE_TABLE", "WORKSPACE_ID", "USER", "REGIONAL_SP_APP_ID")
    if not re.fullmatch(r"\w+\.\w+\.\w+", C.TRACE_TABLE) or not C.WORKSPACE_ID.isdigit():
        raise SystemExit("BEV_TRACE_TABLE must be catalog.schema.table and BEV_WORKSPACE_ID numeric")
    return {"trace_table": C.TRACE_TABLE, "workspace_id": C.WORKSPACE_ID, "env": C.ENV,
            "m365_folder": _check("BEV_M365_FOLDER", C.M365_FOLDER, FOLDER_RE),
            "user_email": _check("BEV_USER", C.USER.lower(), EMAIL_RE),
            "sp_app_id": _check("BEV_REGIONAL_SP_APP_ID", C.REGIONAL_SP_APP_ID, ID_RE).lower()}


class Runner:
    def __init__(self, a):
        self.apply, self.w = a.apply, None
        if a.apply:
            from sqlrun import client
            self.w = client()

    def sql(self, stmt, show_rows=False):
        print("->", stmt if not self.apply else stmt.splitlines()[0][:120])
        if not self.apply:
            return None
        if not C.WAREHOUSE_ID:
            sys.exit("no warehouse id: run the warehouse step first (or set BEV_WAREHOUSE_ID)")
        from sqlrun import run
        out = run(stmt, self.w)
        for row in (out or [])[:20] if show_rows else []:
            print("  ", row)
        return out

    def missing_groups(self):
        if not self.apply:
            return set()
        names = {C.GROUP_ADMIN, C.GROUP_EAST, C.GROUP_WEST}
        found = {n for n in names if list(self.w.groups.list(filter=f'displayName eq "{n}"', attributes="displayName"))}
        for n in sorted(names - found):
            print(f"  WARN group {n!r} not found in the workspace: its grants are skipped (run setup/identities.py)")
        return names - found


def step_sql(r, name, extra=None, missing=frozenset()):
    for stmt in statements(os.path.join(HERE, "sql", SQL[name]), C.sql_params() | (extra or {})):
        if any(f"`{g}`" in stmt for g in missing):
            continue
        r.sql(stmt, show_rows=(name == "test"))


def step_load(r):
    files = sorted(glob.glob(os.path.join(DATA, "*.parquet")))
    if not files:
        sys.exit(f"no parquet in {DATA}: run python data/generate.py first")
    vol = f"/Volumes/{C.CATALOG}/{C.SCHEMA}/{C.VOLUME}"
    for path in files:
        name = os.path.basename(path)[:-8]
        if name not in LOADED:
            continue
        print(f"-> upload {os.path.basename(path)} -> {vol}/pricing/{name}.parquet")
        if r.apply:
            with open(path, "rb") as fh:
                r.w.files.upload(f"{vol}/pricing/{name}.parquet", fh, overwrite=True)
        fq = f"{C.CATALOG}.{C.SCHEMA}.{name}"
        r.sql(f"INSERT OVERWRITE {fq} BY NAME SELECT * EXCEPT (_rescued_data) FROM read_files('{vol}/pricing/{name}.parquet', format => 'parquet')")
        out = r.sql(f"SELECT count(*) FROM {fq}")
        if out:
            print(f"   {fq}: {out[0][0]} rows")


def step_warehouse(r):
    # dedicated serverless warehouse: Foundry sends no warehouse_id, so CAN_USE on this one decides where agent SQL runs
    from databricks.sdk.service.sql import CreateWarehouseRequestWarehouseType, EndpointTagPair, EndpointTags
    kw = dict(name=C.WAREHOUSE_NAME, cluster_size="Small", min_num_clusters=1, max_num_clusters=1, auto_stop_mins=10,
              enable_serverless_compute=True, warehouse_type=CreateWarehouseRequestWarehouseType.PRO,
              tags=EndpointTags(custom_tags=[EndpointTagPair(key=k, value=v) for k, v in C.TAGS.items()]))
    print(f"-> ensure serverless warehouse {C.WAREHOUSE_NAME} (Small, 1 cluster, auto-stop 10 min)")
    if not r.apply:
        return
    found = [w for w in r.w.warehouses.list() if w.name == C.WAREHOUSE_NAME]
    if found:
        # a same-name warehouse without this environment's tags belongs to someone else: do not take it over
        have = {(t.key, t.value) for t in ((found[0].tags.custom_tags or []) if found[0].tags else [])}
        if not set(C.TAGS.items()) <= have:
            sys.exit(f"warehouse {C.WAREHOUSE_NAME} exists without this environment's tags {C.TAGS}: pick a unique BEV_ENV")
        wid = found[0].id
        r.w.warehouses.edit(wid, **kw)
    else:
        wid = r.w.warehouses.create(**kw).response.id
    C.save_resolved(BEV_WAREHOUSE_ID=wid)


def step_warehouse_grant(r, missing):
    from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel
    acl = [WarehouseAccessControlRequest(group_name=g, permission_level=WarehousePermissionLevel.CAN_USE)
           for g in sorted({C.GROUP_ADMIN, C.GROUP_EAST, C.GROUP_WEST} - set(missing))]
    for g in acl:
        print(f"-> warehouse {C.WAREHOUSE_ID or '<id>'} CAN_USE -> {g.group_name}")
    if r.apply and acl:
        r.w.warehouses.update_permissions(C.WAREHOUSE_ID, access_control_list=acl)


def step_tags(r):
    if not C.TAGS:
        return
    pairs = ", ".join(f"'{k}' = '{v}'" for k, v in C.TAGS.items() if "'" not in k + v)
    r.sql(f"ALTER SCHEMA {C.CATALOG}.{C.SCHEMA} SET TAGS ({pairs})")
    for t in TAGGED:
        kind = "VIEW" if t in ("v_price_position", "pricing_kpis") else "TABLE"
        try:
            r.sql(f"ALTER {kind} {C.CATALOG}.{C.SCHEMA}.{t} SET TAGS ({pairs})")
        except Exception as e:  # account tag policies may reject a value: report and keep going
            print("  ERROR", t, type(e).__name__, str(e)[:200])


def main():
    a = args()
    r = Runner(a)
    print(f"setup {'APPLY' if a.apply else 'DRY RUN'} env={C.ENV}: {C.CATALOG}.{C.SCHEMA} (+{C.TRACE_SCHEMA}), "
          f"groups {C.GROUP_ADMIN}/{C.GROUP_EAST}/{C.GROUP_WEST}, steps {a.steps}")
    missing = r.missing_groups() if "grants" in a.steps else set()
    for s in a.steps:
        print(f"\n== {s}")
        if s == "warehouse":
            step_warehouse(r)
        elif s == "load":
            step_load(r)
        elif s == "tags":
            step_tags(r)
        elif s == "grants":
            step_sql(r, s, missing=missing)
            step_warehouse_grant(r, missing)
        elif s in ("policy_sql", "policy_m365"):
            step_sql(r, s, policy_params())
        elif s in ("policy_events", "traffic_views"):
            step_sql(r, s, trace_params())
        else:
            step_sql(r, s)


if __name__ == "__main__":
    main()
