"""Shared loader for the Foundry scripts: targets/<target>.foundry.yml + defaults from setup/config.py."""
import datetime
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "setup"))
import config as C  # noqa: E402


def load_cfg(path=None):
    path = path or os.path.join(C.ROOT, "targets", f"{C.TARGET}.foundry.yml")
    if not os.path.exists(path):
        sys.exit(f"missing {path}: copy targets/example.foundry.yml (and set BEV_TARGET)")
    cfg = yaml.safe_load(open(path)) or {}
    defaults = {"tenant_id": C.TENANT_ID, "databricks_profile": C.PROFILE, "secret_scope": C.SECRET_SCOPE, "tags": C.TAGS,
                "regional_sp_name": C.REGIONAL_SP_NAME, "passthrough_app_name": C.PASSTHROUGH_APP_NAME,
                "ai_audience": "https://ai.azure.com",
                # short-lived client secrets by default (90 days); rotate with provision.py --rotate
                "secret_expiry": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z"),
                "sql_connection": f"bev-sql-mcp-{C.ENV}", "m365_connection": f"bev-m365-mcp-{C.ENV}",
                "sql_toolbox": f"bev-sql-toolbox-{C.ENV}", "m365_toolbox": f"bev-m365-toolbox-{C.ENV}"}
    for k, v in defaults.items():
        if cfg.get(k) in (None, ""):
            cfg[k] = v
    missing = [k for k in ("tenant_id", "subscription_id", "resource_group", "location", "foundry_account", "foundry_project")
               if not cfg.get(k)]
    if missing:
        sys.exit(f"{path}: missing {missing}")
    for k in ("foundry_account", "foundry_project", "resource_group", "sql_connection", "m365_connection", "sql_toolbox", "m365_toolbox"):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", str(cfg[k])):
            sys.exit(f"{path}: {k} must be letters, digits, '.', '_' or '-'")
    return cfg


def project_endpoint(cfg):
    return cfg.get("project_endpoint") or (
        f"https://{cfg['foundry_account']}.services.ai.azure.com/api/projects/{cfg['foundry_project']}")


def agent_vars(cfg):
    """Values for the ${...} placeholders in agent*.yaml."""
    return {"governed_agent": C.AGENT_GOVERNED, "naive_agent": C.AGENT_NAIVE, "catalog": C.CATALOG, "schema": C.SCHEMA, "m365_folder": C.M365_FOLDER, "drive_id": C.M365_DRIVE_ID,
            "policy_doc_id": C.M365_POLICY_DOC_ID, "guardrails_xlsx_id": C.M365_GUARDRAILS_ID,
            "sql_connection": cfg["sql_connection"], "m365_connection": cfg["m365_connection"],
            "sql_toolbox": cfg["sql_toolbox"], "m365_toolbox": cfg["m365_toolbox"]}


def render_agent(path, cfg):
    text, vals = open(path).read(), agent_vars(cfg)
    used = set(re.findall(r"\$\{(\w+)\}", text))
    missing = sorted(k for k in used if not vals.get(k))
    if missing:
        sys.exit(f"{os.path.basename(path)}: no value for {missing} (run the earlier deploy steps or set them in the target)")
    return yaml.safe_load(re.sub(r"\$\{(\w+)\}", lambda m: str(vals[m.group(1)]), text))
