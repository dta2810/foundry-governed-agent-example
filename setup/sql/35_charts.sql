-- Governed charts rendered inside Databricks: a SQL table function reads the row-filtered data as the caller,
-- a Python UDF draws the PNG. One call through the Gateway dbsql MCP; the data never leaves to be plotted elsewhere.

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.render_chart_png(
  chart_type STRING, title STRING, x_label STRING, y_label STRING, data_json STRING, band_low DOUBLE, band_high DOUBLE)
RETURNS STRING
LANGUAGE PYTHON
ENVIRONMENT (dependencies = '["matplotlib==3.9.2"]', environment_version = 'None')
COMMENT 'Draws a clean PNG (base64) from data_json = [{"x":..., "series":..., "y":...}]. chart_type = bar | line. Optional target band shading (band_low/band_high, NULL = none). Used by the chart_* functions; no data access of its own.'
AS $$
import io, json, base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = json.loads(data_json or "[]")
xs = list(dict.fromkeys(str(r["x"]) for r in rows))
series = list(dict.fromkeys(str(r["series"]) for r in rows))
# reference series (guardrails / minimums) are drawn as markers, not bars
ref = [s for s in series if "minimum" in s.lower() or "guardrail" in s.lower()]
main = [s for s in series if s not in ref]
colors = ["#1B3139", "#B9C3C8", "#00A972", "#618794", "#FF3621"]
fig, ax = plt.subplots(figsize=(6, 3.2), dpi=80)
vals_all = [r["y"] for r in rows if r["y"] is not None]
if band_low is not None and band_high is not None:
    ax.axhspan(band_low, band_high, color="#00A972", alpha=0.15, label="Target band")
    vals_all += [band_low, band_high]
if chart_type == "line":
    for i, s in enumerate(main):
        pts = sorted((float(r["x"]), r["y"]) for r in rows if str(r["series"]) == s)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", ms=4, color=colors[i % len(colors)], label=s)
    ax.axhline(0, color="#999999", linewidth=0.8)
else:
    width = 0.8 / max(len(main), 1)
    for i, s in enumerate(main):
        v = {str(r["x"]): r["y"] for r in rows if str(r["series"]) == s}
        ax.bar([j + i * width - 0.4 + width / 2 for j in range(len(xs))], [v.get(x) or 0 for x in xs],
               width=width, color=colors[i % len(colors)], label=s)
    for s in ref:
        v = {str(r["x"]): r["y"] for r in rows if str(r["series"]) == s}
        ax.scatter(range(len(xs)), [v.get(x) for x in xs], marker="_", s=900, linewidths=2.5, color="#FF3621", label=s, zorder=3)
    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels(xs, fontsize=8)
    if band_low is not None and vals_all:
        lo, hi = min(vals_all), max(vals_all)
        pad = (hi - lo) * 0.25 or 5
        ax.set_ylim(lo - pad, hi + pad)
ax.set_title(title, fontsize=10, loc="left")
ax.set_xlabel(x_label, fontsize=8)
ax.set_ylabel(y_label, fontsize=8)
ax.tick_params(labelsize=8)
ax.spines[["top", "right"]].set_visible(False)
if len(series) > 1 or band_low is not None:
    ax.legend(frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(1.0, 1.0))
fig.tight_layout()
buf = io.BytesIO()
fig.savefig(buf, format="png")
plt.close(fig)
return base64.b64encode(buf.getvalue()).decode()
$$;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.chart_price_index(p_market STRING, p_sku STRING)
RETURNS TABLE (chart_title STRING, sku STRING, data_points INT, png_base64 STRING)
COMMENT 'p_market = market code (required for a readable chart); p_sku = SKU or NULL to pick the pair furthest outside its band. Bar chart of the price index vs the competitor pair by channel (last 13 weeks vs prior 13) with the target band shaded. png_base64 = PNG image. Data comes from price_index_vs_pairs (row-filtered for the caller).'
SQL SECURITY DEFINER
RETURN
  WITH r AS (SELECT * FROM ${catalog}.${schema}.price_index_vs_pairs(p_market, p_sku)),
  pick AS (
    SELECT sku FROM r
    ORDER BY CASE status WHEN 'ABOVE BAND' THEN 0 WHEN 'BELOW BAND' THEN 1 ELSE 2 END, abs(price_index_13w - 100) DESC
    LIMIT 1),
  d AS (SELECT r.* FROM r JOIN pick ON pick.sku = r.sku),
  pts AS (
    SELECT channel AS x, 'Last 13 weeks' AS series, price_index_13w AS y FROM d
    UNION ALL SELECT channel, 'Prior 13 weeks', price_index_prior_13w FROM d),
  j AS (SELECT to_json(collect_list(named_struct('x', x, 'series', series, 'y', y))) AS dj FROM pts),
  meta AS (SELECT max(market_id) AS m, max(sku) AS s, max(product_name) AS pn, max(competitor_brand) AS cb,
                  min(target_price_index_low) AS lo, max(target_price_index_high) AS hi, count(*) AS n FROM d)
  SELECT concat(meta.m, ' - ', meta.pn, ' vs ', meta.cb, ': price index by channel'), meta.s, CAST(meta.n AS INT),
         ${catalog}.${schema}.render_chart_png('bar', concat(meta.m, ' - ', meta.pn, ' vs ', meta.cb, ': price index by channel'),
           'Channel', 'Price index (Acme / competitor x 100)',
           j.dj,
           CAST(meta.lo AS DOUBLE), CAST(meta.hi AS DOUBLE))
  FROM meta CROSS JOIN j;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.chart_scenario_grid(p_sku STRING, p_channel STRING, p_market STRING)
RETURNS TABLE (chart_title STRING, data_points INT, png_base64 STRING)
COMMENT 'p_sku required; p_channel / p_market NULL = all. Line chart of the 13-week gross profit change (USD) by price change step, one line per market x channel, from price_scenario_grid (row-filtered for the caller). png_base64 = PNG image.'
SQL SECURITY DEFINER
RETURN
  WITH g AS (SELECT * FROM ${catalog}.${schema}.price_scenario_grid(p_sku, p_channel, p_market)),
  pts AS (SELECT round(price_change_pct * 100, 1) AS x, concat(market_id, ' ', channel) AS series, gp_change_usd_13w AS y FROM g),
  j AS (SELECT to_json(collect_list(named_struct('x', x, 'series', series, 'y', y))) AS dj FROM pts),
  meta AS (SELECT max(product_name) AS pn, count(*) AS n FROM g)
  SELECT concat(meta.pn, ': 13-week GP change by price move'), CAST(meta.n AS INT),
         ${catalog}.${schema}.render_chart_png('line', concat(meta.pn, ': 13-week GP change by price move'),
           'Price change (%)', 'GP change, 13 weeks (USD)',
           j.dj,
           CAST(NULL AS DOUBLE), CAST(NULL AS DOUBLE))
  FROM meta CROSS JOIN j;

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.chart_margin_by_pack(p_market STRING)
RETURNS TABLE (chart_title STRING, data_points INT, png_base64 STRING)
COMMENT 'p_market = market code (required). Bar chart of gross margin % by pack, last 13 weeks vs prior 13 vs the minimum guardrail, from margin_guardrails (row-filtered for the caller). png_base64 = PNG image.'
SQL SECURITY DEFINER
RETURN
  WITH m AS (SELECT * FROM ${catalog}.${schema}.margin_guardrails(p_market, NULL)),
  pts AS (
    SELECT pack_type AS x, 'Last 13 weeks' AS series, round(gm_pct_13w * 100, 1) AS y FROM m
    UNION ALL SELECT pack_type, 'Prior 13 weeks', round(gm_pct_prior_13w * 100, 1) FROM m
    UNION ALL SELECT pack_type, 'Minimum guardrail', round(min_gm_pct * 100, 1) FROM m),
  j AS (SELECT to_json(collect_list(named_struct('x', x, 'series', series, 'y', y))) AS dj FROM pts),
  meta AS (SELECT max(market_id) AS mk, count(*) AS n FROM m)
  SELECT concat(meta.mk, ': gross margin by pack vs guardrail'), CAST(meta.n AS INT),
         ${catalog}.${schema}.render_chart_png('bar', concat(meta.mk, ': gross margin by pack vs guardrail'),
           'Pack', 'Gross margin (%)',
           j.dj,
           CAST(NULL AS DOUBLE), CAST(NULL AS DOUBLE))
  FROM meta CROSS JOIN j;
