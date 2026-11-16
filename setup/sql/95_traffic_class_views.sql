-- Traffic class per Gateway MCP tool call: governed agent vs unguarded agent vs test traffic.
-- Foundry calls arrive with no user agent; scripts/CLI/browser playgrounds send one.
-- Unguarded = the naive agent's signature (write SQL, M365 tools other than read_resource, reads outside the document folder).
-- Needs ${catalog}.${trace_schema}.policy_events (90_policy_events_snapshot.sql) for the text of blocked calls.
CREATE OR REPLACE VIEW ${catalog}.${trace_schema}.mcp_call_traffic
COMMENT 'Gateway MCP tool calls with traffic_class (single place for the agent/test rule).'
AS
WITH u AS (
  SELECT request_id, event_time, requester, requester_type, service_name, mcp_metadata.tool_name AS tool, status_code, latency_ms, user_agent
  FROM system.ai_gateway.usage
  WHERE workspace_id = '${workspace_id}' AND service_type = 'MCP_SERVICE' AND mcp_metadata.json_rpc_method = 'tools/call'
    AND service_name IN ('system.ai.dbsql', 'system.ai.genie_one_mcp', 'system.ai.microsoft_365')
),
q AS (
  SELECT statement_id, start_time, executed_by, statement_text
  FROM system.query.history
  WHERE workspace_id = '${workspace_id}' AND client_application = 'Databricks SQL MCP'
),
-- executed SQL: match statement to the execute_sql call (same caller, start within call latency)
qm AS (
  SELECT u.request_id, q.statement_id, q.statement_text
  FROM u JOIN q ON q.executed_by = u.requester AND u.tool = 'execute_sql'
   AND q.start_time BETWEEN u.event_time - INTERVAL 1 SECOND AND u.event_time + make_interval(0, 0, 0, 0, 0, 0, u.latency_ms / 1000.0 + 2)
),
-- blocked calls never reach query history: take the request text from the policy snapshot
pe AS (SELECT request_id, max(sql_text) AS sql_text FROM ${catalog}.${trace_schema}.policy_events GROUP BY request_id),
c AS (
  SELECT u.*, coalesce(max(qm.statement_text), max(pe.sql_text)) AS request_text
  FROM u LEFT JOIN qm ON qm.request_id = u.request_id LEFT JOIN pe ON pe.request_id = u.request_id
  GROUP BY ALL
)
SELECT c.*,
  CASE
    WHEN user_agent IS NOT NULL THEN 'Test (scripts, CLI, playground)'
    WHEN upper(ltrim(coalesce(request_text, ''))) RLIKE '^(CREATE|INSERT|DELETE|DROP|UPDATE|ALTER|MERGE|TRUNCATE|GRANT|REVOKE)'
      OR (service_name = 'system.ai.microsoft_365' AND tool <> 'read_resource')
      OR (service_name = 'system.ai.microsoft_365' AND request_text IS NOT NULL
          AND request_text NOT LIKE '%/items/%' AND request_text NOT LIKE '%/${m365_folder}/%')
      THEN 'Unguarded agent'
    ELSE 'Governed agent'
  END AS traffic_class
FROM c
;
CREATE OR REPLACE VIEW ${catalog}.${trace_schema}.statement_traffic
COMMENT 'SQL statements run by the Databricks SQL MCP, with the traffic_class of the matching Gateway call.'
AS
SELECT q.statement_id,
  -- one statement can match two calls of the same caller: prefer test, then unguarded
  CASE WHEN max(CASE WHEN c.traffic_class LIKE 'Test%' THEN 1 ELSE 0 END) = 1 THEN 'Test (scripts, CLI, playground)'
       WHEN max(CASE WHEN c.traffic_class LIKE 'Unguarded%' THEN 1 ELSE 0 END) = 1 THEN 'Unguarded agent'
       WHEN count(c.request_id) > 0 THEN 'Governed agent'
       ELSE 'Test (scripts, CLI, playground)' END AS traffic_class
FROM system.query.history q
LEFT JOIN ${catalog}.${trace_schema}.mcp_call_traffic c
  ON c.requester = q.executed_by AND c.tool = 'execute_sql'
 AND q.start_time BETWEEN c.event_time - INTERVAL 1 SECOND AND c.event_time + make_interval(0, 0, 0, 0, 0, 0, c.latency_ms / 1000.0 + 2)
WHERE q.workspace_id = '${workspace_id}'
GROUP BY q.statement_id;
