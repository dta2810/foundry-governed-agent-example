CREATE OR REPLACE TABLE ${catalog}.${schema}.dim_market (
  market_id STRING COMMENT 'Market code (US state).',
  market_name STRING COMMENT 'Market name.',
  region STRING COMMENT 'Sales region.',
  currency STRING COMMENT 'Reporting currency.')
COMMENT 'Markets where Acme Beverages operates (fictitious company).';

CREATE OR REPLACE TABLE ${catalog}.${schema}.dim_product (
  sku STRING COMMENT 'Acme SKU code.',
  brand STRING COMMENT 'Fictitious brand.',
  product_name STRING COMMENT 'Product name with pack and size.',
  pack_type STRING COMMENT 'Pack: Can, PET, Glass or Tetra.',
  pack_size_ml BIGINT COMMENT 'Pack size in millilitres.',
  units_per_case BIGINT COMMENT 'Consumer units per case.',
  list_price_per_case_usd DOUBLE COMMENT 'List price per case in USD.',
  category STRING COMMENT 'Category: Carbonated soft drinks, Water, Juices or Energy drinks.')
COMMENT 'Product catalogue of the fictitious Acme Beverages portfolio (non-alcoholic).';

CREATE OR REPLACE TABLE ${catalog}.${schema}.price_observations (
  week_start DATE COMMENT 'Monday of the observation week.',
  market_id STRING COMMENT 'Market code (US state), joins dim_market.market_id.',
  channel STRING COMMENT 'Modern Trade, Traditional Trade or On-Premise.',
  distributor_id STRING COMMENT 'Distributor serving the channel in the market, joins dim_distributor.distributor_id.',
  retailer STRING COMMENT 'Fictitious retailer banner where the shelf price was observed.',
  sku STRING COMMENT 'Acme SKU code, joins dim_product.sku. Non-alcoholic portfolio only.',
  pack_type STRING COMMENT 'Pack: Can, PET, Glass or Tetra (dim_product.pack_type).',
  shelf_price DOUBLE COMMENT 'Regular consumer shelf price per unit in USD.',
  promo_price DOUBLE COMMENT 'Promoted consumer price per unit in USD; NULL when no promotion ran that week.',
  units BIGINT COMMENT 'Consumer units sold in the week.')
COMMENT 'Weekly shelf and promo price observations with units sold, per market, channel, retailer and SKU.';

CREATE OR REPLACE TABLE ${catalog}.${schema}.competitor_prices (
  week_start DATE COMMENT 'Monday of the observation week.',
  market_id STRING COMMENT 'Market code (US state).',
  channel STRING COMMENT 'Modern Trade, Traditional Trade or On-Premise.',
  competitor_sku STRING COMMENT 'Fictitious competitor SKU code, joins competitor_pairs.competitor_sku.',
  shelf_price DOUBLE COMMENT 'Competitor regular shelf price per unit in USD.',
  promo_price DOUBLE COMMENT 'Competitor promoted price per unit in USD; NULL when not on promotion.')
COMMENT 'Weekly competitor shelf prices for the SKUs in competitor_pairs.';

CREATE OR REPLACE TABLE ${catalog}.${schema}.competitor_pairs (
  pair_id STRING COMMENT 'Competitive pair id.',
  market_id STRING COMMENT 'Market code (US state).',
  sku STRING COMMENT 'Acme SKU code.',
  competitor_brand STRING COMMENT 'Fictitious competitor brand.',
  competitor_sku STRING COMMENT 'Fictitious competitor SKU code.',
  competitor_product_name STRING COMMENT 'Competitor product name.',
  target_price_index_low INT COMMENT 'Lower bound of the target price index (Acme shelf price / competitor shelf price x 100).',
  target_price_index_high INT COMMENT 'Upper bound of the target price index.',
  pair_basis STRING COMMENT 'Why the two SKUs are a pair.')
COMMENT 'Ontology of competitive pairs: each Acme SKU in each market and its reference competitor SKU with the target price index band.';

CREATE OR REPLACE TABLE ${catalog}.${schema}.promo_events (
  promo_event_id STRING COMMENT 'Promotion event id.',
  market_id STRING COMMENT 'Market code (US state).',
  sku STRING COMMENT 'Acme SKU code.',
  pack_type STRING COMMENT 'Pack of the SKU.',
  start_week DATE COMMENT 'First promoted week (Monday).',
  end_week DATE COMMENT 'Last promoted week (Monday).',
  discount_depth_pct DOUBLE COMMENT 'Discount off shelf price, as a fraction (0.20 = 20% off).',
  channels STRING COMMENT 'Channels where the promotion ran, pipe-separated.',
  baseline_units BIGINT COMMENT 'Units expected at regular price during the promo weeks (counterfactual).',
  incremental_units BIGINT COMMENT 'Promoted units minus baseline units.',
  promo_cost DOUBLE COMMENT 'Acme-funded discount on all promoted units plus feature/display fees, USD.',
  gp_uplift DOUBLE COMMENT 'Gross profit during the promotion minus baseline gross profit minus fees, USD. Negative = the promotion destroyed GP.')
COMMENT 'Completed trade promotions with baseline vs incremental volume, cost and gross profit uplift.';

CREATE OR REPLACE TABLE ${catalog}.${schema}.elasticity_estimates (
  sku STRING COMMENT 'Acme SKU code.',
  channel STRING COMMENT 'Modern Trade, Traditional Trade or On-Premise.',
  competitor_sku STRING COMMENT 'Pair competitor SKU used for the cross elasticity.',
  own_elasticity DOUBLE COMMENT 'Own-price elasticity of volume (negative; -2.0 = a 1% price rise loses about 2% of volume).',
  cross_elasticity_vs_pair DOUBLE COMMENT 'Volume elasticity to the pair competitor price (positive; competitor price up = our volume up).',
  r_squared DOUBLE COMMENT 'Fit quality of the estimate.',
  n_weeks INT COMMENT 'Weeks of history used.',
  method STRING COMMENT 'Estimation method.',
  estimated_at DATE COMMENT 'Date of the estimate.')
COMMENT 'Price elasticity estimates per SKU and channel (all markets pooled).';

CREATE OR REPLACE TABLE ${catalog}.${schema}.sku_pnl (
  week_start DATE COMMENT 'Monday of the week.',
  market_id STRING COMMENT 'Market code (US state).',
  channel STRING COMMENT 'Modern Trade, Traditional Trade or On-Premise.',
  sku STRING COMMENT 'Acme SKU code.',
  pack_type STRING COMMENT 'Pack of the SKU.',
  units BIGINT COMMENT 'Consumer units sold.',
  nsv DOUBLE COMMENT 'Net sales value to Acme in USD (after retailer margin and promotional discount).',
  cogs DOUBLE COMMENT 'Cost of goods sold in USD.',
  gp DOUBLE COMMENT 'Gross profit in USD = nsv - cogs.')
COMMENT 'Weekly SKU P&L per market and channel: units, NSV, COGS and gross profit.';

CREATE OR REPLACE TABLE ${catalog}.${schema}.margin_guardrail_thresholds (
  guardrail_id STRING COMMENT 'Guardrail row id.',
  market_id STRING COMMENT 'Market code, or ALL for the company standard. A market row overrides ALL for that pack.',
  pack_type STRING COMMENT 'Pack: Can, PET, Glass or Tetra.',
  min_gm_pct DOUBLE COMMENT 'Minimum gross margin (GP / NSV) as a fraction; below it needs Revenue Growth Management sign-off.',
  target_gm_pct DOUBLE COMMENT 'Target gross margin as a fraction.',
  max_promo_depth_pct DOUBLE COMMENT 'Maximum promotional discount depth as a fraction.',
  effective_from DATE COMMENT 'Date the thresholds apply from.',
  owner_role STRING COMMENT 'Business owner of the thresholds.',
  source_file STRING COMMENT 'Business-owned spreadsheet the thresholds come from.')
COMMENT 'Margin guardrails by pack (and optional market override). Business-owned reference; the same values live in the SharePoint workbook Commercial Guardrails.xlsx.';

CREATE OR REPLACE TABLE ${catalog}.${schema}.playbook_section (
  section_id STRING COMMENT 'Section id (S1..S4).',
  section_order INT COMMENT 'Order of the section in the playbook.',
  title STRING COMMENT 'Section title.',
  objective STRING COMMENT 'What the section must establish.')
COMMENT 'Commercial playbook sections, in the order the review is run.';

CREATE OR REPLACE TABLE ${catalog}.${schema}.playbook_question (
  question_id STRING COMMENT 'Question id (Q01..).',
  section_id STRING COMMENT 'Section the question belongs to, joins playbook_section.',
  question_order INT COMMENT 'Order inside the section.',
  question STRING COMMENT 'The question to answer.',
  outcome_required STRING COMMENT 'What a complete answer contains.',
  data_to_consider STRING COMMENT 'Data the answer should use.',
  suggested_tool STRING COMMENT 'Governed function(s) or metric view that answer it.')
COMMENT 'Commercial playbook questions, each mapped to the governed tool that answers it.';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.playbook_answer (
  answer_id STRING COMMENT 'Answer id.',
  question_id STRING COMMENT 'Question answered, joins playbook_question.',
  asked_by STRING COMMENT 'User the answer was produced for.',
  asked_at TIMESTAMP COMMENT 'When the answer was produced.',
  evidence STRING COMMENT 'Facts and numbers the conclusion rests on.',
  conclusion STRING COMMENT 'Answer to the question.',
  opportunity_flag BOOLEAN COMMENT 'True when the answer surfaces a commercial opportunity or risk.',
  status STRING COMMENT 'draft, reviewed or rejected.',
  sources STRING COMMENT 'Tools and tables used, comma-separated.',
  trace_id STRING COMMENT 'MLflow trace id of the agent turn that produced it.')
COMMENT 'Playbook answers written by the agent (through the app service principal only).';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.user_market_access (
  principal STRING COMMENT 'User email or account group name.',
  market_id STRING COMMENT 'Market code the principal may see, or ALL.',
  note STRING COMMENT 'Why the access exists.')
COMMENT 'Row-filter mapping: which principals may see which markets in the pricing tables. Never granted to the user groups.'
