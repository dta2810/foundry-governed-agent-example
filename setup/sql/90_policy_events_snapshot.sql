-- Snapshot of Unity Gateway policy decisions for this workspace, taken from the metastore's unified trace table.
-- Keeps policy evidence stable when the trace table belongs to someone else. Re-run to refresh (CREATE OR REPLACE).
-- ${trace_table} = <catalog>.<schema>.unity_gateway_otel_spans configured for the metastore.
CREATE OR REPLACE TABLE ${catalog}.${trace_schema}.policy_events
COMMENT 'Unity Gateway policy_evaluated events for system.ai.dbsql and system.ai.microsoft_365 calls of this environment (${env}) (snapshot of the unified trace table).'
AS
SELECT
  s.time AS event_time,
  variant_get(s.attributes, '$["databricks.request_id"]', 'string') AS request_id,
  variant_get(s.attributes, '$["enduser.id"]', 'string') AS identity,
  variant_get(s.attributes, '$["databricks.requester_type"]', 'string') AS requester_type,
  s.service_name AS mcp_service,
  variant_get(s.attributes, '$["gen_ai.tool.name"]', 'string') AS tool,
  coalesce(variant_get(parse_json(variant_get(s.attributes, '$["gen_ai.tool.call.arguments"]', 'string')), '$.query', 'string'),
           variant_get(parse_json(variant_get(s.attributes, '$["gen_ai.tool.call.arguments"]', 'string')), '$.resource_uri', 'string'),
           variant_get(s.attributes, '$["gen_ai.tool.call.arguments"]', 'string')) AS sql_text,
  variant_get(e.attributes, '$["policy.name"]', 'string') AS policy_name,
  variant_get(e.attributes, '$["policy.type"]', 'string') AS policy_type,
  variant_get(e.attributes, '$["policy.phase"]', 'string') AS phase,
  variant_get(e.attributes, '$["policy.action"]', 'string') AS action,
  variant_get(e.attributes, '$["policy.dry_run_action"]', 'string') AS dry_run_action,
  coalesce(variant_get(e.attributes, '$["policy.reason"]', 'string'),
           variant_get(e.attributes, '$["policy.dry_run_reason"]', 'string')) AS reason,
  CASE WHEN variant_get(e.attributes, '$["policy.action"]', 'string') = 'DENY' THEN 'Blocked'
       WHEN variant_get(e.attributes, '$["policy.dry_run_action"]', 'string') = 'DENY' THEN 'Detected (log mode)'
       ELSE 'Allowed' END AS decision
FROM ${trace_table} s
LATERAL VIEW explode(s.events) ev AS e
WHERE e.name = 'policy_evaluated'
  AND variant_get(s.attributes, '$["workspace_id"]', 'string') = '${workspace_id}'
  AND s.service_name IN ('system.ai.dbsql', 'system.ai.microsoft_365')
  AND coalesce(variant_get(e.attributes, '$["policy.name"]', 'string'), '') LIKE '%\_${env}'
  -- only this environment's identities: other callers of the shared service are evaluated too, keep their requests out
  AND lower(coalesce(variant_get(s.attributes, '$["enduser.id"]', 'string'), '')) IN ('${user_email}', '${sp_app_id}')
