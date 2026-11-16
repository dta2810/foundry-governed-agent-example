-- Unity Gateway service policy for system.ai.dbsql (Beta; needs the "Unity Gateway Service Policies" workspace preview).
-- Scoped to the example identities only: the Foundry OAuth passthrough client, the regional SP and the example user
-- (actor.run_as = email for OBO calls, compared lowercased). Every other caller is ALLOWed, so attaching it to a shared
-- metastore's system.ai.dbsql does not change anyone else's behaviour.
-- For the scoped identities: only execute_sql / poll_sql_result; one statement, no comments, no write/DDL keyword, and the
-- pricing schema must be named. This is defense in depth on top of Unity Catalog grants, which remain the read/write boundary
-- (deploy with an owner identity other than the example user so UC also refuses writes).
-- CEL subset only: no subqueries, no regex, no concat, two-arg COALESCE. Whitespace cannot be normalised, so keywords are
-- matched without a trailing space; the few that collide with legitimate identifiers (created, granted, comments,
-- call_signature, execute_sql) are matched with each separator instead.
CREATE OR REPLACE FUNCTION ${catalog}.${schema}.policy_agent_governed_sql(event VARIANT)
RETURNS VARIANT
LANGUAGE SQL
COMMENT 'Service policy for system.ai.dbsql: for the agent identities (Foundry passthrough client / regional SP / example user), allow only single read statements on the governed pricing schema; ALLOW everyone else.'
RETURN
  CASE
    WHEN event:type::string <> 'request' THEN to_variant_object(named_struct('result', 'ALLOW', 'reason', ''))
    WHEN NOT (CAST(COALESCE(event:context.actor.context.client_id, '') AS STRING) = '${agent_client_id}'
              OR CAST(COALESCE(event:context.actor.run_as, '') AS STRING) = '${agent_sp_app_id}'
              OR LOWER(CAST(COALESCE(event:context.actor.run_as, '') AS STRING)) = '${user_email}')
      THEN to_variant_object(named_struct('result', 'ALLOW', 'reason', ''))
    WHEN NOT (CAST(COALESCE(event:context.tool.name, '') AS STRING) = 'execute_sql'
              OR CAST(COALESCE(event:context.tool.name, '') AS STRING) = 'poll_sql_result')
      THEN to_variant_object(named_struct('result', 'DENY', 'reason', 'Policy: the pricing agent may only run and poll read queries.'))
    WHEN CAST(COALESCE(event:context.tool.name, '') AS STRING) = 'poll_sql_result'
      THEN to_variant_object(named_struct('result', 'ALLOW', 'reason', ''))
    WHEN CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), ';')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), '--')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), '/*')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'insert')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'update')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'delete')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'merge')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'drop')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'alter')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'revoke')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'truncate')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'copy')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'replace')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'optimize')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'vacuum')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'restore')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'refresh')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'msck')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'undrop')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'unset')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'immediate')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'create ')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'create\t')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'create\n')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'create\r')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'create(')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'grant ')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'grant\t')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'grant\n')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'grant\r')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'grant(')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'comment ')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'comment\t')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'comment\n')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'comment\r')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'comment(')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'call ')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'call\t')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'call\n')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'call\r')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'call(')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'execute ')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'execute\t')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'execute\n')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'execute\r')
      OR CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), 'execute(')
      THEN to_variant_object(named_struct('result', 'DENY', 'reason', 'Policy: the pricing agent is read-only (one statement, no comments, no write or DDL keywords).'))
    WHEN NOT CONTAINS(LOWER(CAST(COALESCE(event:context.tool.arguments.query, '') AS STRING)), '${catalog}.${schema}.')
      THEN to_variant_object(named_struct('result', 'DENY', 'reason', 'Policy: the pricing agent may only query ${catalog}.${schema}.'))
    ELSE to_variant_object(named_struct('result', 'ALLOW', 'reason', ''))
  END
