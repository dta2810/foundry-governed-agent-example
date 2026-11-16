CREATE OR REPLACE FUNCTION ${catalog}.${schema}.price_index_vs_pairs(p_market STRING, p_sku STRING)
RETURNS TABLE (market_id STRING, channel STRING, sku STRING, product_name STRING, competitor_brand STRING, competitor_sku STRING,
               our_shelf_price_13w DOUBLE, competitor_shelf_price_13w DOUBLE, price_index_13w DOUBLE, price_index_prior_13w DOUBLE,
               target_price_index_low INT, target_price_index_high INT, units_13w BIGINT, units_prior_13w BIGINT,
               volume_change_pct DOUBLE, status STRING)
COMMENT 'p_market = market code (e.g. TX) or NULL/empty for all markets. p_sku = SKU code (e.g. FZ-COLA-355C), exact product name, or NULL/empty for all. Shelf price index vs the competitive pair (Acme / competitor x 100, volume-weighted) per channel for the last 13 weeks and the prior 13, against the pair target band, with the volume change. status = ABOVE BAND, BELOW BAND or IN BAND. Ordered by distance outside the band.'
SQL SECURITY DEFINER
RETURN
  WITH mx AS (SELECT max(week_start) AS w FROM ${catalog}.${schema}.price_observations),
  pp AS (
    SELECT v.*, CASE WHEN v.week_start > mx.w - INTERVAL 91 DAYS THEN 'last' ELSE 'prior' END AS win
    FROM ${catalog}.${schema}.v_price_position v, mx
    WHERE v.week_start > mx.w - INTERVAL 182 DAYS
      AND (coalesce(p_market, '') = '' OR v.market_id = upper(p_market))
      AND (coalesce(p_sku, '') = '' OR v.sku IN (SELECT dp.sku FROM ${catalog}.${schema}.dim_product dp
                                                 WHERE dp.sku = upper(p_sku) OR lower(dp.product_name) = lower(p_sku)))),
  agg AS (
    SELECT market_id, channel, sku, max(competitor_brand) AS competitor_brand, max(competitor_sku) AS competitor_sku,
           max(target_price_index_low) AS lo, max(target_price_index_high) AS hi,
           sum(CASE WHEN win = 'last' THEN shelf_price * units END) / nullif(sum(CASE WHEN win = 'last' THEN units END), 0) AS our_p,
           sum(CASE WHEN win = 'last' THEN competitor_shelf_price * units END) / nullif(sum(CASE WHEN win = 'last' THEN units END), 0) AS comp_p,
           100 * sum(CASE WHEN win = 'last' THEN shelf_price * units END)
               / nullif(sum(CASE WHEN win = 'last' THEN competitor_shelf_price * units END), 0) AS idx_last,
           100 * sum(CASE WHEN win = 'prior' THEN shelf_price * units END)
               / nullif(sum(CASE WHEN win = 'prior' THEN competitor_shelf_price * units END), 0) AS idx_prior,
           sum(CASE WHEN win = 'last' THEN units END) AS u_last, sum(CASE WHEN win = 'prior' THEN units END) AS u_prior
    FROM pp GROUP BY market_id, channel, sku)
  SELECT a.market_id, a.channel, a.sku, dp.product_name, a.competitor_brand, a.competitor_sku,
         round(a.our_p, 2), round(a.comp_p, 2), round(a.idx_last, 1), round(a.idx_prior, 1), a.lo, a.hi,
         CAST(a.u_last AS BIGINT), CAST(a.u_prior AS BIGINT), round(a.u_last / nullif(a.u_prior, 0) - 1, 3),
         CASE WHEN a.idx_last IS NULL THEN 'NO PAIR PRICE' WHEN a.idx_last > a.hi THEN 'ABOVE BAND'
              WHEN a.idx_last < a.lo THEN 'BELOW BAND' ELSE 'IN BAND' END
  FROM agg a LEFT JOIN ${catalog}.${schema}.dim_product dp ON dp.sku = a.sku
  ORDER BY greatest(coalesce(a.idx_last, 0) - a.hi, a.lo - coalesce(a.idx_last, a.lo), 0) DESC, a.market_id, a.sku, a.channel;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.promo_depth_roi(p_market STRING, p_sku STRING)
RETURNS TABLE (promo_event_id STRING, market_id STRING, sku STRING, product_name STRING, pack_type STRING, start_week DATE, end_week DATE,
               discount_depth_pct DOUBLE, max_promo_depth_pct DOUBLE, above_max_depth BOOLEAN, baseline_units BIGINT,
               incremental_units BIGINT, volume_uplift_pct DOUBLE, incremental_share_of_units DOUBLE, promo_cost DOUBLE,
               gp_uplift DOUBLE, gp_roi DOUBLE, depth_band_avg_gp_roi DOUBLE, verdict STRING)
COMMENT 'p_market = market code or NULL/empty for all; p_sku = SKU code, exact product name, or NULL/empty for all. Completed promotions with volume uplift, cost, gross profit uplift and GP ROI (gp_uplift / promo_cost), the pack max-depth guardrail and the average GP ROI of all visible promotions at the same depth. verdict = BUILDS GP or DESTROYS GP. Ordered by depth, then GP uplift.'
SQL SECURITY DEFINER
RETURN
  WITH ev AS (
    -- join instead of IN-subquery: correlated params are not allowed inside a subquery here
    SELECT e.* FROM ${catalog}.${schema}.promo_events e
    LEFT JOIN ${catalog}.${schema}.dim_product dpf ON dpf.sku = e.sku
    WHERE (coalesce(p_market, '') = '' OR e.market_id = upper(p_market))
      AND (coalesce(p_sku, '') = '' OR e.sku = upper(p_sku) OR lower(dpf.product_name) = lower(p_sku))),
  gr AS (
    SELECT e.promo_event_id, g.max_promo_depth_pct,
           row_number() OVER (PARTITION BY e.promo_event_id ORDER BY CASE WHEN g.market_id = 'ALL' THEN 1 ELSE 0 END) AS rn
    FROM ev e JOIN ${catalog}.${schema}.margin_guardrail_thresholds g
      ON g.pack_type = e.pack_type AND g.market_id IN (e.market_id, 'ALL')),
  band AS (SELECT discount_depth_pct, avg(gp_uplift / nullif(promo_cost, 0)) AS roi FROM ${catalog}.${schema}.promo_events GROUP BY discount_depth_pct)
  SELECT e.promo_event_id, e.market_id, e.sku, dp.product_name, e.pack_type, e.start_week, e.end_week, e.discount_depth_pct,
         gr.max_promo_depth_pct, e.discount_depth_pct > gr.max_promo_depth_pct, e.baseline_units, e.incremental_units,
         round(e.incremental_units / nullif(e.baseline_units, 0), 3),
         round(e.incremental_units / nullif(e.baseline_units + e.incremental_units, 0), 3),
         e.promo_cost, e.gp_uplift, round(e.gp_uplift / nullif(e.promo_cost, 0), 3), round(band.roi, 3),
         CASE WHEN e.gp_uplift >= 0 THEN 'BUILDS GP' ELSE 'DESTROYS GP' END
  FROM ev e
  LEFT JOIN gr ON gr.promo_event_id = e.promo_event_id AND gr.rn = 1
  LEFT JOIN band ON band.discount_depth_pct = e.discount_depth_pct
  LEFT JOIN ${catalog}.${schema}.dim_product dp ON dp.sku = e.sku
  ORDER BY e.discount_depth_pct DESC, e.gp_uplift ASC;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.margin_guardrails(p_market STRING, p_pack STRING)
RETURNS TABLE (market_id STRING, pack_type STRING, nsv_13w DOUBLE, gp_13w DOUBLE, gm_pct_13w DOUBLE, gm_pct_prior_13w DOUBLE,
               min_gm_pct DOUBLE, target_gm_pct DOUBLE, gap_to_min_pts DOUBLE, lowest_gm_sku STRING, lowest_sku_gm_pct DOUBLE,
               guardrail_id STRING, guardrail_source STRING, status STRING)
COMMENT 'p_market = market code or NULL/empty for all; p_pack = Can, PET, Glass, Tetra or NULL/empty for all. Gross margin (GP / NSV) per market and pack for the last 13 weeks vs the prior 13, against the guardrail from margin_guardrail_thresholds (market row overrides ALL). gap_to_min_pts in percentage points (negative = below minimum). status = BELOW MIN, BELOW TARGET or OK. Ordered by gap to minimum.'
SQL SECURITY DEFINER
RETURN
  WITH mx AS (SELECT max(week_start) AS w FROM ${catalog}.${schema}.sku_pnl),
  pnl AS (
    SELECT s.*, s.week_start > mx.w - INTERVAL 91 DAYS AS is_last
    FROM ${catalog}.${schema}.sku_pnl s, mx
    WHERE s.week_start > mx.w - INTERVAL 182 DAYS
      AND (coalesce(p_market, '') = '' OR s.market_id = upper(p_market))
      AND (coalesce(p_pack, '') = '' OR lower(s.pack_type) = lower(p_pack))),
  pk AS (
    SELECT market_id, pack_type,
           sum(CASE WHEN is_last THEN nsv END) AS nsv_l, sum(CASE WHEN is_last THEN gp END) AS gp_l,
           sum(CASE WHEN NOT is_last THEN gp END) / nullif(sum(CASE WHEN NOT is_last THEN nsv END), 0) AS gm_p
    FROM pnl GROUP BY market_id, pack_type),
  sk AS (
    SELECT market_id, pack_type, sku, sum(gp) / nullif(sum(nsv), 0) AS gm,
           row_number() OVER (PARTITION BY market_id, pack_type ORDER BY sum(gp) / nullif(sum(nsv), 0)) AS rn
    FROM pnl WHERE is_last GROUP BY market_id, pack_type, sku),
  gr AS (
    SELECT pk.market_id, pk.pack_type, g.guardrail_id, g.min_gm_pct, g.target_gm_pct, g.source_file,
           row_number() OVER (PARTITION BY pk.market_id, pk.pack_type ORDER BY CASE WHEN g.market_id = 'ALL' THEN 1 ELSE 0 END) AS rn
    FROM pk JOIN ${catalog}.${schema}.margin_guardrail_thresholds g
      ON g.pack_type = pk.pack_type AND g.market_id IN (pk.market_id, 'ALL'))
  SELECT pk.market_id, pk.pack_type, round(pk.nsv_l, 0), round(pk.gp_l, 0), round(pk.gp_l / nullif(pk.nsv_l, 0), 3), round(pk.gm_p, 3),
         gr.min_gm_pct, gr.target_gm_pct, round(100 * (pk.gp_l / nullif(pk.nsv_l, 0) - gr.min_gm_pct), 1),
         sk.sku, round(sk.gm, 3), gr.guardrail_id, gr.source_file,
         CASE WHEN gr.min_gm_pct IS NULL THEN 'NO GUARDRAIL' WHEN pk.gp_l / nullif(pk.nsv_l, 0) < gr.min_gm_pct THEN 'BELOW MIN'
              WHEN pk.gp_l / nullif(pk.nsv_l, 0) < gr.target_gm_pct THEN 'BELOW TARGET' ELSE 'OK' END
  FROM pk
  LEFT JOIN gr ON gr.market_id = pk.market_id AND gr.pack_type = pk.pack_type AND gr.rn = 1
  LEFT JOIN sk ON sk.market_id = pk.market_id AND sk.pack_type = pk.pack_type AND sk.rn = 1
  ORDER BY pk.gp_l / nullif(pk.nsv_l, 0) - coalesce(gr.min_gm_pct, 0) ASC;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.price_volume_factor(p_price_change_pct DOUBLE, p_own_elasticity DOUBLE,
                                                                     p_cross_elasticity DOUBLE, p_competitor_price_change_pct DOUBLE)
RETURNS DOUBLE
LANGUAGE PYTHON
DETERMINISTIC
COMMENT 'Internal helper of price_scenario_impact (not granted to users). Constant-elasticity volume multiplier: (1 + price change) ^ own x (1 + competitor change) ^ cross. Changes are fractions, clipped to [-0.5, 0.5]; elasticities clipped to [-6, 0] (own) and [0, 3] (cross).'
AS $$
if p_price_change_pct is None or p_own_elasticity is None:
    return None
dp = max(-0.5, min(0.5, float(p_price_change_pct)))
dc = max(-0.5, min(0.5, float(p_competitor_price_change_pct or 0.0)))
own = max(-6.0, min(0.0, float(p_own_elasticity)))
cross = max(0.0, min(3.0, float(p_cross_elasticity or 0.0)))
return float((1.0 + dp) ** own * (1.0 + dc) ** cross)
$$;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.price_scenario_impact(p_sku STRING, p_channel STRING, p_price_change_pct DOUBLE)
RETURNS TABLE (market_id STRING, channel STRING, sku STRING, product_name STRING, price_change_pct DOUBLE, own_elasticity DOUBLE,
               base_weekly_units DOUBLE, projected_weekly_units DOUBLE, volume_change_pct DOUBLE,
               base_weekly_nsv DOUBLE, projected_weekly_nsv DOUBLE, nsv_change_pct DOUBLE,
               base_weekly_gp DOUBLE, projected_weekly_gp DOUBLE, gp_change_usd DOUBLE, gp_change_pct DOUBLE,
               price_index_13w DOUBLE, projected_price_index DOUBLE, target_price_index_low INT, target_price_index_high INT,
               projected_index_status STRING)
COMMENT 'p_sku = SKU code or exact product name. p_channel = Modern Trade, Traditional Trade, On-Premise, or NULL/empty for all. p_price_change_pct = shelf price change as a fraction (0.05 = +5%; values above 1 are read as percent, 5 = +5%). Projects weekly volume, NSV and gross profit per market and channel from the last-13-week baseline and the own-price elasticity (competitor price held flat), plus the resulting price index vs the pair target band. Scenario only: changes nothing.'
SQL SECURITY DEFINER
RETURN
  WITH chg AS (SELECT greatest(-0.5, least(0.5, CASE WHEN abs(p_price_change_pct) > 1 THEN p_price_change_pct / 100 ELSE p_price_change_pct END)) AS d),
  mx AS (SELECT max(week_start) AS w FROM ${catalog}.${schema}.price_observations),
  base AS (
    SELECT v.market_id, v.channel, v.sku, max(v.target_price_index_low) AS lo, max(v.target_price_index_high) AS hi,
           sum(v.units) / 13.0 AS u, sum(v.nsv) / 13.0 AS nsv, sum(v.cogs) / 13.0 AS cogs,
           100 * sum(v.shelf_price * v.units) / nullif(sum(v.competitor_shelf_price * v.units), 0) AS idx
    FROM ${catalog}.${schema}.v_price_position v, mx
    WHERE v.week_start > mx.w - INTERVAL 91 DAYS
      AND v.sku IN (SELECT dp.sku FROM ${catalog}.${schema}.dim_product dp WHERE dp.sku = upper(p_sku) OR lower(dp.product_name) = lower(p_sku))
      AND (coalesce(p_channel, '') = '' OR lower(v.channel) = lower(p_channel))
    GROUP BY v.market_id, v.channel, v.sku),
  proj AS (
    SELECT b.*, e.own_elasticity, chg.d,
           ${catalog}.${schema}.price_volume_factor(chg.d, e.own_elasticity, e.cross_elasticity_vs_pair, 0.0) AS f
    FROM base b JOIN ${catalog}.${schema}.elasticity_estimates e ON e.sku = b.sku AND e.channel = b.channel, chg)
  SELECT p.market_id, p.channel, p.sku, dp.product_name, round(p.d, 4), p.own_elasticity,
         round(p.u, 0), round(p.u * p.f, 0), round(p.f - 1, 3),
         round(p.nsv, 0), round(p.nsv * (1 + p.d) * p.f, 0), round((1 + p.d) * p.f - 1, 3),
         round(p.nsv - p.cogs, 0), round(p.nsv * (1 + p.d) * p.f - p.cogs * p.f, 0),
         round((p.nsv * (1 + p.d) * p.f - p.cogs * p.f) - (p.nsv - p.cogs), 0),
         round(((p.nsv * (1 + p.d) * p.f - p.cogs * p.f) - (p.nsv - p.cogs)) / nullif(p.nsv - p.cogs, 0), 3),
         round(p.idx, 1), round(p.idx * (1 + p.d), 1), p.lo, p.hi,
         CASE WHEN p.idx IS NULL THEN 'NO PAIR PRICE' WHEN p.idx * (1 + p.d) > p.hi THEN 'ABOVE BAND'
              WHEN p.idx * (1 + p.d) < p.lo THEN 'BELOW BAND' ELSE 'IN BAND' END
  FROM proj p LEFT JOIN ${catalog}.${schema}.dim_product dp ON dp.sku = p.sku
  ORDER BY p.market_id, p.channel;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.playbook_questions(p_section_id STRING)
RETURNS TABLE (section_id STRING, section_order INT, section_title STRING, section_objective STRING, question_id STRING,
               question_order INT, question STRING, outcome_required STRING, data_to_consider STRING, suggested_tool STRING)
COMMENT 'p_section_id = S1..S4 or NULL/empty for the whole playbook. The commercial playbook questions in order, each with the outcome required, the data to consider and the governed tool that answers it. playbook_evidence(p_market) returns compact evidence for all 12 questions in one call.'
SQL SECURITY DEFINER
RETURN
  SELECT s.section_id, s.section_order, s.title, s.objective, q.question_id, q.question_order, q.question,
         q.outcome_required, q.data_to_consider, q.suggested_tool
  FROM ${catalog}.${schema}.playbook_question q JOIN ${catalog}.${schema}.playbook_section s ON s.section_id = q.section_id
  WHERE coalesce(p_section_id, '') = '' OR s.section_id = upper(p_section_id)
  ORDER BY s.section_order, q.question_order;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.kpi_13w_vs_prior(p_market STRING)
RETURNS TABLE (market_id STRING, is_total BOOLEAN, sku STRING, product_name STRING, pack_type STRING, channel STRING,
               volume_units_13w BIGINT, volume_units_prior_13w BIGINT, volume_change_pct DOUBLE,
               nsv_13w DOUBLE, nsv_prior_13w DOUBLE, nsv_change_pct DOUBLE,
               gp_13w DOUBLE, gp_prior_13w DOUBLE, gp_change_usd DOUBLE,
               gm_pct_13w DOUBLE, gm_pct_prior_13w DOUBLE, gm_change_pts DOUBLE)
COMMENT 'p_market = market code (e.g. TX) or NULL/empty for all markets. Volume, NSV, gross profit and gross margin for the last 13 weeks vs the prior 13 (windows relative to the latest week in sku_pnl), one row per market x SKU x pack x channel plus one market total row (is_total = true; sku, product_name, pack_type, channel NULL). volume_units_* in consumer units over 13 weeks; nsv_* and gp_* in USD over 13 weeks; gp_change_usd = gp_13w - gp_prior_13w in USD. volume_change_pct and nsv_change_pct are FRACTIONS (0.05 = +5%, -0.20 = -20%). gm_pct_* = GP / NSV as a FRACTION (0.42 = 42%). gm_change_pts = change in gross margin in percentage points (-2.5 = margin down 2.5 points). Ordered by market, total row first, then GP change (worst first).'
SQL SECURITY DEFINER
RETURN
  WITH mx AS (SELECT max(week_start) AS w FROM ${catalog}.${schema}.sku_pnl),
  pnl AS (
    SELECT s.*, s.week_start > mx.w - INTERVAL 91 DAYS AS is_last
    FROM ${catalog}.${schema}.sku_pnl s, mx
    WHERE s.week_start > mx.w - INTERVAL 182 DAYS
      AND (coalesce(p_market, '') = '' OR s.market_id = upper(p_market))),
  g AS (
    SELECT market_id, false AS is_total, sku, pack_type, channel,
           sum(CASE WHEN is_last THEN units END) AS u_l, sum(CASE WHEN NOT is_last THEN units END) AS u_p,
           sum(CASE WHEN is_last THEN nsv END) AS n_l, sum(CASE WHEN NOT is_last THEN nsv END) AS n_p,
           sum(CASE WHEN is_last THEN gp END) AS g_l, sum(CASE WHEN NOT is_last THEN gp END) AS g_p
    FROM pnl GROUP BY market_id, sku, pack_type, channel
    UNION ALL
    SELECT market_id, true, NULL, NULL, NULL,
           sum(CASE WHEN is_last THEN units END), sum(CASE WHEN NOT is_last THEN units END),
           sum(CASE WHEN is_last THEN nsv END), sum(CASE WHEN NOT is_last THEN nsv END),
           sum(CASE WHEN is_last THEN gp END), sum(CASE WHEN NOT is_last THEN gp END)
    FROM pnl GROUP BY market_id)
  SELECT g.market_id, g.is_total, g.sku, dp.product_name, g.pack_type, g.channel,
         CAST(g.u_l AS BIGINT), CAST(g.u_p AS BIGINT), round(g.u_l / nullif(g.u_p, 0) - 1, 4),
         round(g.n_l, 0), round(g.n_p, 0), round(g.n_l / nullif(g.n_p, 0) - 1, 4),
         round(g.g_l, 0), round(g.g_p, 0), round(coalesce(g.g_l, 0) - coalesce(g.g_p, 0), 0),
         round(g.g_l / nullif(g.n_l, 0), 4), round(g.g_p / nullif(g.n_p, 0), 4),
         round(100 * (g.g_l / nullif(g.n_l, 0) - g.g_p / nullif(g.n_p, 0)), 2)
  FROM g LEFT JOIN ${catalog}.${schema}.dim_product dp ON dp.sku = g.sku
  ORDER BY g.market_id, g.is_total DESC, coalesce(g.g_l, 0) - coalesce(g.g_p, 0) ASC, g.sku, g.channel;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.price_scenario_grid(p_sku STRING, p_channel STRING, p_market STRING)
RETURNS TABLE (market_id STRING, channel STRING, sku STRING, product_name STRING, price_change_pct DOUBLE, own_elasticity DOUBLE,
               price_index_13w DOUBLE, projected_price_index DOUBLE, target_price_index_low INT, target_price_index_high INT,
               projected_index_status STRING, volume_change_pct DOUBLE, nsv_change_pct DOUBLE,
               gp_change_usd_weekly DOUBLE, gp_change_usd_13w DOUBLE, is_min_cut_into_band BOOLEAN)
COMMENT 'p_sku = SKU code (e.g. FZ-COLA-355C), exact product name, or NULL/empty for all SKUs. p_channel = Modern Trade, Traditional Trade, On-Premise, or NULL/empty for all. p_market = market code or NULL/empty for all. Same model as price_scenario_impact (last-13-week baseline, own-price elasticity, competitor price held flat) run for a fixed grid of shelf price changes -0.10, -0.07, -0.05, -0.03, 0, +0.03, +0.05, one row per market x channel x SKU x step. price_change_pct, volume_change_pct and nsv_change_pct are FRACTIONS (-0.05 = -5%). price_index_13w and projected_price_index in index points (Acme / pair competitor shelf price x 100) vs the target band target_price_index_low..high; projected_index_status = ABOVE BAND, BELOW BAND, IN BAND or NO PAIR PRICE. gp_change_usd_weekly = projected minus baseline gross profit per week in USD; gp_change_usd_13w = weekly x 13 in USD. is_min_cut_into_band = true on the smallest price cut (negative step) that brings an index that is out of band today IN BAND for that market x channel x SKU, false on the other steps, NULL on every step when the index is already in band or no cut in the grid lands in band. Scenario only: changes nothing.'
SQL SECURITY DEFINER
RETURN
  WITH mx AS (SELECT max(week_start) AS w FROM ${catalog}.${schema}.price_observations),
  steps AS (SELECT explode(array(-0.10D, -0.07D, -0.05D, -0.03D, 0.0D, 0.03D, 0.05D)) AS d),
  -- SKU resolved in its own CTE and joined (no IN-subquery, no param filter above a join): keeps the function callable from playbook_evidence
  sel AS (
    SELECT DISTINCT sku FROM ${catalog}.${schema}.elasticity_estimates
    WHERE coalesce(p_sku, '') = '' OR sku = upper(p_sku)
    UNION
    SELECT dp.sku FROM ${catalog}.${schema}.dim_product dp WHERE lower(dp.product_name) = lower(p_sku)),
  vp AS (
    SELECT v.* FROM ${catalog}.${schema}.v_price_position v, mx
    WHERE v.week_start > mx.w - INTERVAL 91 DAYS
      AND (coalesce(p_channel, '') = '' OR lower(v.channel) = lower(p_channel))
      AND (coalesce(p_market, '') = '' OR v.market_id = upper(p_market))),
  base AS (
    SELECT v.market_id, v.channel, v.sku, max(v.target_price_index_low) AS lo, max(v.target_price_index_high) AS hi,
           sum(v.units) / 13.0 AS u, sum(v.nsv) / 13.0 AS nsv, sum(v.cogs) / 13.0 AS cogs,
           100 * sum(v.shelf_price * v.units) / nullif(sum(v.competitor_shelf_price * v.units), 0) AS idx
    FROM vp v JOIN sel ON sel.sku = v.sku
    GROUP BY v.market_id, v.channel, v.sku),
  proj AS (
    SELECT b.*, e.own_elasticity, s.d,
           -- price_volume_factor math inlined (competitor flat, so the cross term is 1): avoids a Python UDF round trip per row
           power(1 + greatest(-0.5D, least(0.5D, s.d)), greatest(-6.0D, least(0.0D, e.own_elasticity))) AS f,
           CASE WHEN b.idx IS NULL THEN 'NO PAIR PRICE' WHEN b.idx * (1 + s.d) > b.hi THEN 'ABOVE BAND'
                WHEN b.idx * (1 + s.d) < b.lo THEN 'BELOW BAND' ELSE 'IN BAND' END AS st
    FROM base b JOIN ${catalog}.${schema}.elasticity_estimates e ON e.sku = b.sku AND e.channel = b.channel CROSS JOIN steps s),
  mc AS (
    -- only pairs out of band today (step 0 not IN BAND): max(d) over the negative steps in band = the smallest absolute cut
    SELECT p.*,
           CASE WHEN max(CASE WHEN p.d = 0 AND p.st <> 'IN BAND' THEN 1 END) OVER (PARTITION BY p.market_id, p.channel, p.sku) = 1
                THEN max(CASE WHEN p.d < 0 AND p.st = 'IN BAND' THEN p.d END) OVER (PARTITION BY p.market_id, p.channel, p.sku) END AS d_min
    FROM proj p)
  SELECT p.market_id, p.channel, p.sku, dp.product_name, round(p.d, 4), p.own_elasticity,
         round(p.idx, 1), round(p.idx * (1 + p.d), 1), p.lo, p.hi, p.st,
         round(p.f - 1, 4), round((1 + p.d) * p.f - 1, 4),
         round((p.nsv * (1 + p.d) * p.f - p.cogs * p.f) - (p.nsv - p.cogs), 1),
         round(13 * ((p.nsv * (1 + p.d) * p.f - p.cogs * p.f) - (p.nsv - p.cogs)), 0),
         CASE WHEN p.d_min IS NULL THEN NULL ELSE p.d = p.d_min END
  FROM mc p
  LEFT JOIN ${catalog}.${schema}.dim_product dp ON dp.sku = p.sku
  ORDER BY p.market_id, p.sku, p.channel, p.d;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.playbook_evidence(p_market STRING)
RETURNS TABLE (market_id STRING, question_id STRING, section_id STRING, metric STRING, subject STRING, value DOUBLE, unit STRING,
               status STRING, note STRING)
COMMENT 'p_market = market code (e.g. TX; expected use is one market) or NULL/empty for all markets. Compact evidence for all 12 playbook questions in one call, built from kpi_13w_vs_prior, margin_guardrails, price_index_vs_pairs, promo_depth_roi and price_scenario_grid: one row per market x question x evidence item, top items only. Q01 market totals; Q02 top 5 SKUs by absolute GP change and GM change per pack; Q03 packs below guardrail plus a count row; Q04 out-of-band pairs plus a count row; Q05 volume change of those pairs vs the market; Q06 top 3 headroom pairs; Q07 GP uplift by promo depth; Q08 promotions above the max depth plus a count row; Q09 incremental share of promoted units; Q10/Q11 the smallest grid price cut that brings each above-band pair into band; Q12 one synthesis row with the top issue. metric = what value measures; subject = SKU | channel, pack, promo id, depth or market total. unit: fraction (0.05 = 5%, also used for GP ROI = GP uplift / promo cost), usd_13w (USD over 13 weeks), usd_weekly, usd (USD per promotion), index_points (Acme / pair competitor shelf price x 100), units_13w (consumer units over 13 weeks), pts (percentage points), count. status = UP/DOWN/FLAT for changes, the band/guardrail/verdict status of the source function, or TOP ISSUE for Q12. note = the context needed to read the value. Ordered by market, question, item.'
SQL SECURITY DEFINER
RETURN
  -- nested functions are called with literal NULLs and the market is filtered once at the end:
  -- passing p_market through raises ACCESSING_OUTER_QUERY_COLUMN_IS_NOT_ALLOWED in the nested bodies
  WITH k AS (SELECT * FROM ${catalog}.${schema}.kpi_13w_vs_prior(NULL)),
  pi AS (SELECT * FROM ${catalog}.${schema}.price_index_vs_pairs(NULL, NULL)),
  pr AS (SELECT * FROM ${catalog}.${schema}.promo_depth_roi(NULL, NULL)),
  mg AS (SELECT * FROM ${catalog}.${schema}.margin_guardrails(NULL, NULL)),
  gr AS (SELECT * FROM ${catalog}.${schema}.price_scenario_grid(NULL, NULL, NULL) WHERE is_min_cut_into_band),
  tot AS (SELECT * FROM k WHERE is_total),
  ob AS (
    SELECT pi.*,
           row_number() OVER (PARTITION BY market_id ORDER BY greatest(price_index_13w - target_price_index_high, target_price_index_low - price_index_13w) DESC, sku, channel) AS r_dist,
           row_number() OVER (PARTITION BY market_id ORDER BY volume_change_pct, sku, channel) AS r_vol
    FROM pi WHERE status IN ('ABOVE BAND', 'BELOW BAND')),
  cut AS (
    SELECT o.market_id, o.sku, o.channel, o.price_index_13w AS idx, o.target_price_index_low AS lo, o.target_price_index_high AS hi,
           g.price_change_pct, g.projected_price_index, g.projected_index_status, g.volume_change_pct, g.nsv_change_pct,
           g.gp_change_usd_weekly, g.gp_change_usd_13w,
           row_number() OVER (PARTITION BY o.market_id ORDER BY o.sku, o.channel) AS r
    FROM pi o LEFT JOIN gr g ON g.market_id = o.market_id AND g.sku = o.sku AND g.channel = o.channel
    WHERE o.status = 'ABOVE BAND'),
  sk AS (
    SELECT market_id, sku, max(product_name) AS pn, max(pack_type) AS pack,
           sum(gp_13w) - sum(gp_prior_13w) AS dgp, sum(gp_13w) / nullif(sum(nsv_13w), 0) AS gm_l,
           sum(gp_prior_13w) / nullif(sum(nsv_prior_13w), 0) AS gm_p,
           row_number() OVER (PARTITION BY market_id ORDER BY abs(sum(gp_13w) - sum(gp_prior_13w)) DESC, sku) AS rn
    FROM k WHERE NOT is_total GROUP BY market_id, sku),
  pk AS (
    SELECT market_id, pack_type, sum(gp_13w) - sum(gp_prior_13w) AS dgp, sum(gp_13w) / nullif(sum(nsv_13w), 0) AS gm_l,
           sum(gp_prior_13w) / nullif(sum(nsv_prior_13w), 0) AS gm_p
    FROM k WHERE NOT is_total GROUP BY market_id, pack_type),
  hr AS (
    SELECT p.*, p.target_price_index_high - p.price_index_13w AS room,
           row_number() OVER (PARTITION BY p.market_id ORDER BY p.target_price_index_high - p.price_index_13w DESC, p.sku, p.channel) AS rn
    FROM pi p WHERE p.status IN ('BELOW BAND', 'IN BAND') AND coalesce(p.volume_change_pct, 0) >= -0.05),
  inc AS (
    SELECT pr.*, row_number() OVER (PARTITION BY market_id ORDER BY incremental_share_of_units ASC, promo_event_id) AS rn,
           row_number() OVER (PARTITION BY market_id ORDER BY above_max_depth DESC, gp_uplift, promo_event_id) AS r_gp
    FROM pr),
  pa AS (
    SELECT market_id, discount_depth_pct, grouping(discount_depth_pct) AS g, count(*) AS n, avg(gp_uplift) AS avg_gp, avg(gp_roi) AS avg_roi,
           sum(gp_uplift) AS sum_gp, count_if(above_max_depth) AS n_above, sum(incremental_units) AS inc_u,
           sum(baseline_units + incremental_units) AS tot_u
    FROM pr GROUP BY GROUPING SETS ((market_id, discount_depth_pct), (market_id))),
  cand AS (
    SELECT market_id, 1 AS prio, -gap_to_min_pts AS sev, pack_type AS subject, 'gm_gap_to_min' AS metric, gap_to_min_pts AS value, 'pts' AS unit,
           concat(pack_type, ' gross margin ', format_string('%.1f', 100 * gm_pct_13w), '% is below the ', format_string('%.0f', 100 * min_gm_pct),
                  '% minimum (was ', format_string('%.1f', 100 * gm_pct_prior_13w), '%): restore margin before any price or promo move. See Q03.') AS note
    FROM mg WHERE status = 'BELOW MIN'
    UNION ALL
    SELECT market_id, 2, idx - hi, concat(sku, ' | ', channel), 'gp_change_usd_13w', gp_change_usd_13w, 'usd_13w',
           concat('Index ', format_string('%.1f', idx), ' is above the ', lo, '-', hi, ' band. ',
                  coalesce(concat('A ', format_string('%.0f', 100 * price_change_pct), '% price cut brings it to ',
                                  format_string('%.1f', projected_price_index), ' with GP ', format_string('%+.0f', gp_change_usd_13w), ' USD over 13 weeks.'),
                           'No cut in the grid brings it into band.'), ' See Q04, Q05, Q11.')
    FROM cut
    UNION ALL
    SELECT market_id, 3, -gp_uplift, promo_event_id, 'gp_uplift', gp_uplift, 'usd',
           concat(sku, ' promotion at ', format_string('%.0f', 100 * discount_depth_pct), '% depth broke the ', format_string('%.0f', 100 * max_promo_depth_pct),
                  '% maximum and lost ', format_string('%.0f', -gp_uplift), ' USD of GP. See Q07, Q08.')
    FROM inc WHERE above_max_depth AND gp_uplift < 0
    UNION ALL
    SELECT market_id, 4, target_price_index_low - price_index_13w, concat(sku, ' | ', channel), 'price_index_13w', price_index_13w, 'index_points',
           concat('Index ', format_string('%.1f', price_index_13w), ' is below the ', target_price_index_low, '-', target_price_index_high,
                  ' band with stable volume: price headroom. See Q06, Q10.')
    FROM pi WHERE status = 'BELOW BAND' AND coalesce(volume_change_pct, 0) >= -0.05),
  top AS (
    SELECT c.*, count(*) OVER (PARTITION BY market_id) AS n, row_number() OVER (PARTITION BY market_id ORDER BY prio, sev DESC, subject) AS rn
    FROM cand c),
  ev AS (
    -- Q01 market totals
    SELECT t.market_id, 'Q01' AS question_id, 'S1' AS section_id, x.metric, 'market total' AS subject, x.value, x.unit,
           CASE WHEN x.metric NOT LIKE '%change%' THEN NULL WHEN x.value > 0 THEN 'UP' WHEN x.value < 0 THEN 'DOWN' ELSE 'FLAT' END AS status,
           x.note, x.ord
    FROM tot t LATERAL VIEW stack(6,
      'volume_units_13w', CAST(t.volume_units_13w AS DOUBLE), 'units_13w', concat('prior 13w ', t.volume_units_prior_13w, ' units'), 1,
      'volume_change_pct', t.volume_change_pct, 'fraction', 'last 13w vs prior 13w', 2,
      'nsv_13w', t.nsv_13w, 'usd_13w', concat('prior 13w ', format_string('%.0f', t.nsv_prior_13w), ' USD'), 3,
      'nsv_change_pct', t.nsv_change_pct, 'fraction', 'last 13w vs prior 13w', 4,
      'gp_change_usd', t.gp_change_usd, 'usd_13w', concat('GP ', format_string('%.0f', t.gp_prior_13w), ' -> ', format_string('%.0f', t.gp_13w), ' USD'), 5,
      'gm_change_pts', t.gm_change_pts, 'pts', concat('GM ', format_string('%.1f', 100 * t.gm_pct_prior_13w), '% -> ', format_string('%.1f', 100 * t.gm_pct_13w), '%'), 6
    ) x AS metric, value, unit, note, ord
    UNION ALL
    -- Q02 top 5 SKUs by absolute GP change, then GM change per pack
    SELECT market_id, 'Q02', 'S1', 'gp_change_usd', sku, round(dgp, 0), 'usd_13w',
           CASE WHEN dgp > 0 THEN 'UP' WHEN dgp < 0 THEN 'DOWN' ELSE 'FLAT' END,
           concat(pn, ' (', pack, '): GM ', format_string('%.1f', 100 * gm_p), '% -> ', format_string('%.1f', 100 * gm_l), '%'), rn
    FROM sk WHERE rn <= 5
    UNION ALL
    SELECT market_id, 'Q02', 'S1', 'gm_change_pts', pack_type, round(100 * (gm_l - gm_p), 2), 'pts',
           CASE WHEN gm_l > gm_p THEN 'UP' WHEN gm_l < gm_p THEN 'DOWN' ELSE 'FLAT' END,
           concat('GM ', format_string('%.1f', 100 * gm_p), '% -> ', format_string('%.1f', 100 * gm_l), '%; GP change ', format_string('%.0f', dgp), ' USD over 13w'),
           10 + row_number() OVER (PARTITION BY market_id ORDER BY gm_l - gm_p)
    FROM pk
    UNION ALL
    -- Q03 guardrail breaches + count
    SELECT market_id, 'Q03', 'S1', 'gap_to_min_pts', pack_type, gap_to_min_pts, 'pts', status,
           concat('GM ', format_string('%.1f', 100 * gm_pct_13w), '% (prior ', format_string('%.1f', 100 * gm_pct_prior_13w), '%) vs min ',
                  format_string('%.0f', 100 * min_gm_pct), '% / target ', format_string('%.0f', 100 * target_gm_pct), '%; lowest SKU ',
                  coalesce(lowest_gm_sku, '-'), '; guardrail ', coalesce(guardrail_id, '-')),
           row_number() OVER (PARTITION BY market_id ORDER BY gap_to_min_pts)
    FROM mg WHERE status <> 'OK'
    UNION ALL
    SELECT market_id, 'Q03', 'S1', 'packs_below_guardrail', 'all packs', CAST(count_if(status <> 'OK') AS DOUBLE), 'count',
           CASE WHEN count_if(status = 'BELOW MIN') > 0 THEN 'BELOW MIN' WHEN count_if(status <> 'OK') > 0 THEN 'BELOW TARGET' ELSE 'OK' END,
           concat(count(*), ' packs checked'), 0
    FROM mg GROUP BY market_id
    UNION ALL
    -- Q04 / Q05 out-of-band pairs: index vs band, and the volume change where it drifted
    SELECT o.market_id, x.question_id, 'S2', x.metric, concat(o.sku, ' | ', o.channel), x.value, x.unit, o.status, x.note, x.ord
    FROM ob o LATERAL VIEW stack(2,
      'Q04', 'price_index_13w', o.price_index_13w, 'index_points',
      concat('band ', o.target_price_index_low, '-', o.target_price_index_high, '; prior 13w ', coalesce(format_string('%.1f', o.price_index_prior_13w), '-'),
             '; vs ', o.competitor_brand, ' ', o.competitor_sku), o.r_dist,
      'Q05', 'volume_change_pct', o.volume_change_pct, 'fraction',
      concat('index ', coalesce(format_string('%.1f', o.price_index_prior_13w), '-'), ' -> ', format_string('%.1f', o.price_index_13w),
             '; units ', coalesce(CAST(o.units_prior_13w AS STRING), '-'), ' -> ', coalesce(CAST(o.units_13w AS STRING), '-')), o.r_vol
    ) x AS question_id, metric, value, unit, note, ord
    UNION ALL
    SELECT market_id, 'Q04', 'S2', 'pairs_out_of_band', 'all pairs', CAST(count_if(status IN ('ABOVE BAND', 'BELOW BAND')) AS DOUBLE), 'count',
           CASE WHEN count_if(status IN ('ABOVE BAND', 'BELOW BAND')) > 0 THEN 'OUT OF BAND' ELSE 'IN BAND' END,
           concat(count(*), ' SKU x channel pairs checked'), 0
    FROM pi GROUP BY market_id
    UNION ALL
    SELECT market_id, 'Q05', 'S2', 'market_volume_change_pct', 'market total', volume_change_pct, 'fraction',
           CASE WHEN volume_change_pct > 0 THEN 'UP' WHEN volume_change_pct < 0 THEN 'DOWN' ELSE 'FLAT' END, 'benchmark: all SKUs and channels', 0
    FROM tot
    UNION ALL
    -- Q06 top 3 headroom pairs
    SELECT market_id, 'Q06', 'S2', 'index_headroom_to_band_high', concat(sku, ' | ', channel), round(room, 1), 'index_points', status,
           concat('index ', format_string('%.1f', price_index_13w), ', band ', target_price_index_low, '-', target_price_index_high,
                  ', volume change ', coalesce(format_string('%+.1f', 100 * volume_change_pct), '-'), '%'), rn
    FROM hr WHERE rn <= 3
    UNION ALL
    -- Q07 GP by promo depth
    SELECT market_id, 'Q07', 'S3', 'avg_gp_uplift_per_promo', concat('depth ', format_string('%.2f', discount_depth_pct)), round(avg_gp, 0), 'usd',
           CASE WHEN avg_gp >= 0 THEN 'BUILDS GP' ELSE 'DESTROYS GP' END,
           concat(n, ' promotions; avg GP ROI ', coalesce(format_string('%.2f', avg_roi), '-'), '; total GP uplift ', format_string('%.0f', sum_gp), ' USD'),
           discount_depth_pct
    FROM pa WHERE g = 0
    UNION ALL
    -- Q08 count of promotions above the max depth; Q09 incremental share of all promoted units
    SELECT a.market_id, x.question_id, 'S3', x.metric, 'all promotions', x.value, x.unit, x.status, x.note, 0
    FROM pa a LATERAL VIEW stack(2,
      'Q08', 'promos_above_max_depth', CAST(a.n_above AS DOUBLE), 'count', CASE WHEN a.n_above > 0 THEN 'BREACH' ELSE 'OK' END,
      concat(a.n, ' promotions checked'),
      'Q09', 'incremental_share_of_promo_units', round(a.inc_u / nullif(a.tot_u, 0), 3), 'fraction', CAST(NULL AS STRING),
      concat(a.inc_u, ' incremental of ', a.tot_u, ' promoted units in ', a.n, ' promotions')
    ) x AS question_id, metric, value, unit, status, note
    WHERE a.g = 1
    UNION ALL
    -- Q08 promotions above the max depth; Q09 the 3 most subsidised promotions (lowest incremental share)
    SELECT i.market_id, x.question_id, 'S3', x.metric, i.promo_event_id, x.value, x.unit, i.verdict, x.note, x.ord
    FROM inc i LATERAL VIEW stack(2,
      'Q08', 'gp_uplift', i.gp_uplift, 'usd',
      concat(i.sku, ' ', i.pack_type, ': depth ', format_string('%.2f', i.discount_depth_pct), ' vs max ', format_string('%.2f', i.max_promo_depth_pct),
             '; volume uplift ', coalesce(format_string('%+.0f', 100 * i.volume_uplift_pct), '-'), '%; GP ROI ', coalesce(format_string('%.2f', i.gp_roi), '-'),
             '; from ', CAST(i.start_week AS STRING)), i.r_gp,
      'Q09', 'incremental_share_of_units', i.incremental_share_of_units, 'fraction',
      concat(i.sku, ' at depth ', format_string('%.2f', i.discount_depth_pct), ': ', i.incremental_units, ' incremental of ',
             i.baseline_units + i.incremental_units, ' units'), i.rn
    ) x AS question_id, metric, value, unit, note, ord
    WHERE (x.question_id = 'Q08' AND i.above_max_depth) OR (x.question_id = 'Q09' AND i.rn <= 3)
    UNION ALL
    -- Q10 / Q11 smallest grid cut into band per above-band pair (Q10 only where such a cut exists)
    SELECT c.market_id, x.question_id, 'S4', x.metric, concat(c.sku, ' | ', c.channel), x.value, x.unit,
           coalesce(c.projected_index_status, 'NO CUT IN GRID'), x.note, c.r
    FROM cut c LATERAL VIEW stack(2,
      'Q10', 'gp_change_usd_13w', c.gp_change_usd_13w, 'usd_13w',
      concat('price ', format_string('%+.0f', 100 * c.price_change_pct), '%: index ', format_string('%.1f', c.idx), ' -> ',
             format_string('%.1f', c.projected_price_index), '; volume ', format_string('%+.1f', 100 * c.volume_change_pct), '%; NSV ',
             format_string('%+.1f', 100 * c.nsv_change_pct), '%; GP ', format_string('%+.1f', c.gp_change_usd_weekly), ' USD/week'),
      'Q11', 'min_price_cut_into_band', c.price_change_pct, 'fraction',
      CASE WHEN c.price_change_pct IS NULL THEN concat('index ', format_string('%.1f', c.idx), ': no step down to -10% reaches the ', c.lo, '-', c.hi, ' band')
           ELSE concat('smallest cut in the grid into the ', c.lo, '-', c.hi, ' band: index ', format_string('%.1f', c.idx), ' -> ',
                       format_string('%.1f', c.projected_price_index), '; GP ', format_string('%+.0f', c.gp_change_usd_13w), ' USD over 13w') END
    ) x AS question_id, metric, value, unit, note
    WHERE x.question_id = 'Q11' OR c.price_change_pct IS NOT NULL
    UNION ALL
    -- Q12 synthesis: the top flagged issue (margin breach > index above band > GP-destroying deep promo > headroom)
    SELECT market_id, 'Q12', 'S4', concat('top_issue:', metric), subject, value, unit, 'TOP ISSUE',
           concat(note, ' Other flagged issues: ', n - 1, '.'), 0
    FROM top WHERE rn = 1
    UNION ALL
    SELECT t.market_id, 'Q12', 'S4', 'top_issue:none', 'market total', t.gp_change_usd, 'usd_13w', 'OK',
           'No guardrail breach, out-of-band pair or GP-destroying deep promotion flagged.', 0
    FROM tot t LEFT ANTI JOIN cand c ON c.market_id = t.market_id)
  SELECT market_id, question_id, section_id, metric, subject, CAST(value AS DOUBLE), unit, status, note
  FROM ev
  WHERE coalesce(p_market, '') = '' OR market_id = upper(p_market)
  ORDER BY market_id, question_id, ord, subject
