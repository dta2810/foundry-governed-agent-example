-- Unity Gateway service policy for system.ai.microsoft_365 (Beta; CEL subset only: no concat/regex/subqueries).
-- Scoped to the example identities: the Foundry OAuth passthrough client and the example user (actor.run_as = email,
-- compared lowercased). Every other caller is ALLOWed, because system.ai.* services are metastore-wide.
-- For the scoped identities: only read_resource, and only the exact resource URIs the agent template uses (folder listing,
-- policy document, guardrails workbook; the draft document only when the optional injection scene is deployed).
-- Exact equality, no substring match: any other path or query string is denied.
-- Attach via PATCH .../mcp-services/system.ai.microsoft_365?update_mask=config.service_policies (setup/policies.py).
CREATE OR REPLACE FUNCTION ${catalog}.${schema}.policy_m365_pricing_docs(event VARIANT)
RETURNS VARIANT
LANGUAGE SQL
COMMENT 'Service policy for system.ai.microsoft_365: for the agent identities, allow only read_resource on the exact approved pricing document URIs; ALLOW everyone else.'
RETURN
  CASE
    WHEN event:type::string <> 'request' THEN to_variant_object(named_struct('result', 'ALLOW', 'reason', ''))
    WHEN NOT (CAST(COALESCE(event:context.actor.context.client_id, '') AS STRING) = '${agent_client_id}'
              OR LOWER(CAST(COALESCE(event:context.actor.run_as, '') AS STRING)) = '${user_email}')
      THEN to_variant_object(named_struct('result', 'ALLOW', 'reason', ''))
    WHEN CAST(COALESCE(event:context.tool.name, '') AS STRING) <> 'read_resource'
      THEN to_variant_object(named_struct('result', 'DENY', 'reason', 'Policy: the pricing agent may only read the approved pricing documents (mail, calendar, Teams, people and search are blocked).'))
    WHEN CAST(COALESCE(event:context.tool.arguments.resource_uri, '') AS STRING) = '/v1.0/me/drive/root:/${folder_path}:/children'
      OR CAST(COALESCE(event:context.tool.arguments.resource_uri, '') AS STRING) = '/v1.0/drives/${drive_id}/items/${policy_doc_id}/content'
      OR CAST(COALESCE(event:context.tool.arguments.resource_uri, '') AS STRING) = '/v1.0/me/drive/items/${guardrails_xlsx_id}/workbook/worksheets/Guardrails/usedRange?$select=values'${draft_clause}
      THEN to_variant_object(named_struct('result', 'ALLOW', 'reason', ''))
    ELSE to_variant_object(named_struct('result', 'DENY', 'reason', 'Policy: only the approved pricing documents may be read.'))
  END
