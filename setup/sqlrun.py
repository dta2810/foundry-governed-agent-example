"""SQL helpers: render ${param} placeholders and run statements on the target warehouse."""
import re
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

import config


def client():
    return WorkspaceClient(profile=config.PROFILE)


def run(sql, w):
    r = w.statement_execution.execute_statement(warehouse_id=config.WAREHOUSE_ID, statement=sql, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}\n{sql[:400]}")
    return r.result.data_array if r.result else None


def render(text, params):
    missing = sorted({m for m in re.findall(r"\$\{(\w+)\}", text) if m not in params})
    if missing:
        raise SystemExit(f"unrendered SQL parameters {missing}")
    return re.sub(r"\$\{(\w+)\}", lambda m: str(params[m.group(1)]), text)


def statements(path, params):
    return [s.strip() for s in render(open(path).read(), params).split(";\n") if s.strip()]
