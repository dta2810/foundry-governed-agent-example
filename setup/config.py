"""Deployment parameters for one target.

Values come from targets/<target>.env (you write it) and targets/<target>.resolved.env (written by the scripts:
ids of the warehouse, Entra apps and SharePoint files). Select the target with BEV_TARGET=<target>.
Every resource name carries the BEV_ENV suffix, so several environments can share one workspace.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.environ.get("BEV_TARGET", "")


def _env_file(suffix):
    return os.path.join(ROOT, "targets", f"{TARGET}{suffix}") if TARGET else ""


def _load(path):
    if path and os.path.exists(path):
        for line in open(path):
            line = line.split(" #", 1)[0].strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load(_env_file(".env"))
_load(_env_file(".resolved.env"))


def get(key, default=""):
    return os.environ.get(key) or default


# Required per target: names are account- and metastore-wide, so pick a suffix nobody else uses (no shared default)
ENV = get("BEV_ENV")
if TARGET and not ENV:
    raise SystemExit(f"set BEV_ENV in targets/{TARGET}.env: a short suffix unique to you (for example your initials + 1)")
ENV = ENV or "local"  # unit tests only
if not re.fullmatch(r"[a-z0-9]{1,12}", ENV):
    raise SystemExit("BEV_ENV must be 1-12 lowercase letters/digits")

# Databricks workspace
PROFILE = get("DATABRICKS_CONFIG_PROFILE", "DEFAULT")
ACCOUNT_PROFILE = get("BEV_ACCOUNT_PROFILE")
HOST = get("BEV_HOST").rstrip("/")            # use the adb-<id>.<n> host: vanity hosts redirect Entra tokens on /ai-gateway
WORKSPACE_ID = get("BEV_WORKSPACE_ID")
CATALOG = get("BEV_CATALOG")
SCHEMA = get("BEV_SCHEMA", f"bev_pricing_{ENV}")
TRACE_SCHEMA = get("BEV_TRACE_SCHEMA", f"bev_traces_{ENV}")
VOLUME = get("BEV_VOLUME", "landing")
TRACE_TABLE = get("BEV_TRACE_TABLE")          # <catalog>.<schema>.<table> of the metastore's unified Gateway trace table
WAREHOUSE_NAME = get("BEV_WAREHOUSE_NAME", f"bev-pricing-wh-{ENV}")
WAREHOUSE_ID = get("BEV_WAREHOUSE_ID")        # resolved by the warehouse step
SECRET_SCOPE = get("BEV_SECRET_SCOPE", f"bev-pricing-{ENV}")
GROUP_ADMIN = get("BEV_GROUP_ADMIN", f"bev_pricing_admin_{ENV}")
GROUP_EAST = get("BEV_GROUP_EAST", f"bev_pricing_east_{ENV}")
GROUP_WEST = get("BEV_GROUP_WEST", f"bev_pricing_west_{ENV}")
USER = get("BEV_USER").lower()      # email of the example user (policies are scoped to this identity)

# Entra (resolved by infra/foundry/provision.py)
TENANT_ID = get("BEV_TENANT_ID")
REGIONAL_SP_NAME = get("BEV_REGIONAL_SP_NAME", f"bev-pricing-regional-sp-{ENV}")
PASSTHROUGH_APP_NAME = get("BEV_PASSTHROUGH_APP_NAME", f"bev-foundry-passthrough-{ENV}")
REGIONAL_SP_APP_ID = get("BEV_REGIONAL_SP_APP_ID")
PASSTHROUGH_APP_ID = get("BEV_PASSTHROUGH_APP_ID")

# Microsoft 365 document folder (ids resolved by scripts/resolve_sharepoint.py)
M365_FOLDER = get("BEV_M365_FOLDER", "acme-beverages-docs")
M365_DRIVE_ID = get("BEV_M365_DRIVE_ID")
M365_FOLDER_ID = get("BEV_M365_FOLDER_ID")
M365_POLICY_DOC_ID = get("BEV_M365_POLICY_DOC_ID")
M365_GUARDRAILS_ID = get("BEV_M365_GUARDRAILS_ID")
M365_DRAFT_DOC_ID = get("BEV_M365_DRAFT_DOC_ID")

# Foundry agent names (per environment, so two environments never share an agent)
AGENT_GOVERNED = f"bev-pricing-governed-{ENV}"
AGENT_NAIVE = f"bev-pricing-naive-{ENV}"

TAGS = json.loads(get("BEV_TAGS", json.dumps({"bev_project": f"governed_agent_{ENV}", "owner": "unset"})))

ADB_RESOURCE_APP = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"  # Azure Databricks first-party app (public, same in every tenant)


# one validator for every operator-supplied value that reaches SQL, SCIM filters, Graph paths or resource names
_PATTERNS = {
    "CATALOG": r"[A-Za-z0-9_]+", "SCHEMA": r"[A-Za-z0-9_]+", "TRACE_SCHEMA": r"[A-Za-z0-9_]+", "VOLUME": r"[A-Za-z0-9_]+",
    "TRACE_TABLE": r"\w+\.\w+\.\w+", "WORKSPACE_ID": r"\d+", "WAREHOUSE_ID": r"[0-9a-f]+",
    "GROUP_ADMIN": r"[A-Za-z0-9_-]+", "GROUP_EAST": r"[A-Za-z0-9_-]+", "GROUP_WEST": r"[A-Za-z0-9_-]+",
    "WAREHOUSE_NAME": r"[A-Za-z0-9_-]+", "SECRET_SCOPE": r"[A-Za-z0-9_.-]+",
    "REGIONAL_SP_NAME": r"[A-Za-z0-9_-]+", "PASSTHROUGH_APP_NAME": r"[A-Za-z0-9_-]+",
    "USER": r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", "TENANT_ID": r"[0-9a-f-]{36}",
    "REGIONAL_SP_APP_ID": r"[0-9a-f-]{36}", "PASSTHROUGH_APP_ID": r"[0-9a-f-]{36}",
    "M365_FOLDER": r"[A-Za-z0-9][A-Za-z0-9 _-]*(/[A-Za-z0-9][A-Za-z0-9 _-]*)*",
    "M365_DRIVE_ID": r"[A-Za-z0-9!_-]{8,}", "M365_FOLDER_ID": r"[A-Za-z0-9!_-]{8,}", "M365_POLICY_DOC_ID": r"[A-Za-z0-9!_-]{8,}",
    "M365_GUARDRAILS_ID": r"[A-Za-z0-9!_-]{8,}", "M365_DRAFT_DOC_ID": r"[A-Za-z0-9!_-]{8,}",
}


def validate():
    bad = [k for k, rx in _PATTERNS.items() if globals().get(k) and not re.fullmatch(rx, globals()[k])]
    if bad:
        raise SystemExit(f"invalid settings {bad}: check targets/{TARGET or '<target>'}.env / .resolved.env")


validate()


def require(*names):
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit(f"missing settings {missing}: set them in targets/{TARGET or '<target>'}.env (see targets/example.env)")


def save_resolved(**values):
    """Persist ids produced by a script into targets/<target>.resolved.env (gitignored) and the current process."""
    if not TARGET:
        print("BEV_TARGET not set: resolved values not saved:", values)
        return
    path = _env_file(".resolved.env")
    cur = {}
    if os.path.exists(path):
        for line in open(path):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1)
                cur[k] = v
    for k, v in values.items():
        cur[k] = str(v)
        os.environ[k] = str(v)
        globals()[k.replace("BEV_", "", 1)] = str(v)
    validate()
    with open(path, "w") as fh:
        fh.write("# written by the deploy scripts; safe to delete (re-run the steps to rebuild)\n")
        fh.writelines(f"{k}={v}\n" for k, v in sorted(cur.items()))
    print(f"saved {sorted(values)} -> targets/{os.path.basename(path)}")


def sql_params():
    return {"catalog": CATALOG, "schema": SCHEMA, "trace_schema": TRACE_SCHEMA, "volume": VOLUME,
            "group_admin": GROUP_ADMIN, "group_east": GROUP_EAST, "group_west": GROUP_WEST}
