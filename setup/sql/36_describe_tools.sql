-- Tool catalog served from Unity Catalog metadata: the agent reads functions, parameters, output columns and semantics
-- (the COMMENTs) in one governed call, instead of a column catalog hand-copied into every agent prompt.
CREATE OR REPLACE FUNCTION ${catalog}.${schema}.describe_tools()
RETURNS TABLE (tool STRING, call_signature STRING, returns STRING, description STRING)
COMMENT 'Catalog of the governed pricing tools in this schema: one row per table function with its call signature (parameters in order), output columns with types, and its documented semantics (units, status values, NULL = all). Call it once before choosing a tool.'
SQL SECURITY DEFINER
RETURN
  WITH r AS (
    SELECT specific_name, routine_name, full_data_type, comment
    FROM ${catalog}.information_schema.routines
    WHERE routine_schema = '${schema}' AND data_type = 'TABLE_TYPE'
      AND routine_name NOT IN ('describe_tools', 'zz_tmp_probe')
      AND routine_name NOT LIKE 'policy_%' AND routine_name NOT LIKE 'rf_%'
      -- chart_* return PNGs for image-capable clients (App MCP ImageContent); text-only agents draw from data instead
      AND routine_name NOT LIKE 'chart_%'),
  p AS (
    SELECT specific_name, concat_ws(', ', transform(array_sort(collect_list(struct(ordinal_position, concat(parameter_name, ' ', data_type)))), x -> x.col2)) AS params
    FROM ${catalog}.information_schema.parameters
    WHERE specific_schema = '${schema}' AND coalesce(is_result, 'NO') = 'NO'
    GROUP BY specific_name)
  SELECT r.routine_name,
         concat('${catalog}.${schema}.', r.routine_name, '(', coalesce(p.params, ''), ')'),
         r.full_data_type,
         r.comment
  FROM r LEFT JOIN p ON p.specific_name = r.specific_name
  UNION ALL
  SELECT 'pricing_kpis (metric view)',
         concat('SELECT <dims>, MEASURE(<measure>) FROM ${catalog}.${schema}.pricing_kpis GROUP BY <dims>'),
         'measures: volume_units, nsv_usd, gp_usd, gm_pct (fraction), avg_price_usd',
         'Governed KPIs by market_id, channel, brand, sku, pack_type, week_start. Always aggregate with MEASURE().';
