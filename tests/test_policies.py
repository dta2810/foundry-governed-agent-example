"""Gateway policy functions: render them and replay known bypass payloads against their rules (no cloud access)."""
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "setup"))
import config as C  # noqa: E402
import run_setup as R  # noqa: E402
from sqlrun import statements  # noqa: E402

IDS = {"USER": "First.Last@Example.com", "PASSTHROUGH_APP_ID": "11111111-aaaa-bbbb-cccc-000000000001",
       "REGIONAL_SP_APP_ID": "22222222-aaaa-bbbb-cccc-000000000002", "M365_FOLDER": "acme-beverages-docs",
       "M365_DRIVE_ID": "b!driveABCDEFGH123", "M365_POLICY_DOC_ID": "01POLICYDOC0001", "M365_GUARDRAILS_ID": "01GUARDRAILS001",
       "M365_DRAFT_DOC_ID": "", "CATALOG": "cat"}


@pytest.fixture
def ids(monkeypatch):
    for k, v in IDS.items():
        monkeypatch.setattr(C, k, v)
    return monkeypatch


def render(name):
    p = C.sql_params() | R.policy_params()
    (stmt,) = statements(os.path.join(R.HERE, "sql", R.SQL[name]), p)
    return stmt


def sql_terms(stmt):
    """The deny terms of the read-only rule, as Python strings (SQL escapes \\t \\n \\r decoded)."""
    block = stmt.split("WHEN CONTAINS(", 1)[1].split("THEN", 1)[0]
    raw = re.findall(r"AS STRING\)\), '((?:[^']|'')*)'\)", "CONTAINS(" + block)
    return [t.replace("\\t", "\t").replace("\\n", "\n").replace("\\r", "\r") for t in raw]


def sql_allowed(stmt, query):
    q = query.lower()
    return not any(t in q for t in sql_terms(stmt)) and f"{C.CATALOG}.{C.SCHEMA}." in q


BYPASSES = [
    "DROP\tTABLE cat.{s}.price_observations", "DROP\nTABLE cat.{s}.price_observations", "drop/**/table cat.{s}.x",
    "INSERT\nINTO cat.{s}.x SELECT 1", "CREATE\tTABLE cat.{s}.x AS SELECT 1", "CREATE OR REPLACE VIEW cat.{s}.v AS SELECT 1",
    "EXECUTE IMMEDIATE 'DROP TABLE cat.{s}.x'", "COPY INTO cat.{s}.x FROM '/tmp'", "REVOKE SELECT ON cat.{s}.x FROM g",
    "GRANT\tSELECT ON cat.{s}.x TO g", "SELECT 1 FROM cat.{s}.x; DROP TABLE cat.{s}.x", "OPTIMIZE cat.{s}.x",
    "SELECT * FROM other.hr.salaries -- cat.{s}.", "SELECT * FROM other.hr.salaries /* cat.{s}. */",
    "ALTER TABLE cat.{s}.x SET TAGS ('a'='b')", "CALL\tcat.{s}.p()", "COMMENT ON TABLE cat.{s}.x IS 'x'",
    "MERGE INTO cat.{s}.x USING y ON true WHEN MATCHED THEN DELETE", "SELECT * FROM other.hr.salaries",
]
LEGIT = [
    "SELECT * FROM cat.{s}.describe_tools()",
    "SELECT tool, call_signature, returns FROM cat.{s}.describe_tools() LIMIT 50",
    "SELECT market_id, channel, status FROM cat.{s}.price_index_vs_pairs('TX', 'FZ-COLA-355C') LIMIT 50",
    "SELECT * FROM cat.{s}.playbook_evidence('TX')",
    "SELECT market_id, MEASURE(nsv_usd) AS nsv FROM cat.{s}.pricing_kpis GROUP BY market_id",
    "WITH g AS (SELECT * FROM cat.{s}.price_scenario_grid('FZ-COLA-355C', 'Modern Trade', 'TX')) SELECT * FROM g WHERE is_min_cut_into_band",
]


def test_sql_policy_blocks_known_bypasses(ids):
    stmt = render("policy_sql")
    for q in BYPASSES:
        assert not sql_allowed(stmt, q.format(s=C.SCHEMA)), q


def test_sql_policy_allows_the_agent_queries(ids):
    stmt = render("policy_sql")
    for q in LEGIT:
        assert sql_allowed(stmt, q.format(s=C.SCHEMA)), q
    # the shipped SQL tests are the agent's query shapes too
    for q in statements(os.path.join(R.HERE, "sql", "60_test_functions.sql"), C.sql_params()):
        q = "\n".join(line for line in q.splitlines() if not line.lstrip().startswith("--"))  # file comments, not agent SQL
        assert sql_allowed(stmt, q), q[:80]


def test_sql_policy_scoping(ids):
    stmt = render("policy_sql")
    assert "LOWER(CAST(COALESCE(event:context.actor.run_as, '') AS STRING)) = 'first.last@example.com'" in stmt
    assert "= 'poll_sql_result'" in stmt and "may only run and poll read queries" in stmt  # any other tool is denied


def m365_allowed_uris(stmt):
    return set(re.findall(r"resource_uri, ''\) AS STRING\) = '([^']*)'", stmt))


def test_m365_policy_is_exact_uri_allow_list(ids):
    stmt = render("policy_m365")
    assert "CONTAINS" not in stmt and "__unset__" not in stmt
    assert m365_allowed_uris(stmt) == {
        "/v1.0/me/drive/root:/acme-beverages-docs:/children",
        "/v1.0/drives/b!driveABCDEFGH123/items/01POLICYDOC0001/content",
        "/v1.0/me/drive/items/01GUARDRAILS001/workbook/worksheets/Guardrails/usedRange?$select=values"}
    for bad in ("/v1.0/me/messages?x=1", "/v1.0/me/messages?$search=acme-beverages-docs",
                "/v1.0/me/drive/root:/acme-beverages-docs-private:/children", "/v1.0/me/drive/root/children",
                "/v1.0/drives/b!driveABCDEFGH123/items/01POLICYDOC0001/content?x=1"):
        assert bad not in m365_allowed_uris(stmt)


def test_m365_policy_scopes_user_and_passthrough_client(ids):
    stmt = render("policy_m365")
    assert "event:context.actor.context.client_id, '') AS STRING) = '11111111-aaaa-bbbb-cccc-000000000001'" in stmt
    assert "LOWER(CAST(COALESCE(event:context.actor.run_as, '') AS STRING)) = 'first.last@example.com'" in stmt


def test_m365_draft_clause_only_when_set(ids):
    assert not any("DRAFT" in u for u in m365_allowed_uris(render("policy_m365")))
    ids.setattr(C, "M365_DRAFT_DOC_ID", "01DRAFTDOC00001")
    assert "/v1.0/drives/b!driveABCDEFGH123/items/01DRAFTDOC00001/content" in m365_allowed_uris(render("policy_m365"))


@pytest.mark.parametrize("key,value", [("M365_FOLDER", "/"), ("M365_FOLDER", "a/../b"), ("M365_FOLDER", "x'y"),
                                       ("M365_DRIVE_ID", "a"), ("USER", "not-an-email"), ("PASSTHROUGH_APP_ID", "x' OR '1")])
def test_policy_params_reject_bad_values(ids, key, value):
    ids.setattr(C, key, value)
    with pytest.raises(SystemExit):
        R.policy_params()


def test_evidence_snapshot_scoped_to_env_identities(ids, monkeypatch):
    monkeypatch.setattr(C, "TRACE_TABLE", "a.b.c")
    monkeypatch.setattr(C, "WORKSPACE_ID", "123")
    (stmt,) = statements(os.path.join(R.HERE, "sql", R.SQL["policy_events"]), C.sql_params() | R.trace_params())
    assert "IN ('first.last@example.com', '22222222-aaaa-bbbb-cccc-000000000002')" in stmt
