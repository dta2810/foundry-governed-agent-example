CREATE OR REPLACE VIEW ${catalog}.${schema}.v_price_position
COMMENT 'Weekly Acme vs pair price position per market, channel and SKU, with units and P&L. Source of the pricing_kpis metric view.'
AS
SELECT o.week_start, o.market_id, o.channel, o.distributor_id, o.retailer, o.sku, o.pack_type,
       o.shelf_price, coalesce(o.promo_price, o.shelf_price) AS effective_price, o.promo_price IS NOT NULL AS on_promo, o.units,
       p.pair_id, p.competitor_brand, p.competitor_sku, p.target_price_index_low, p.target_price_index_high,
       c.shelf_price AS competitor_shelf_price, coalesce(c.promo_price, c.shelf_price) AS competitor_effective_price,
       s.nsv, s.cogs, s.gp
FROM ${catalog}.${schema}.price_observations o
LEFT JOIN ${catalog}.${schema}.competitor_pairs p ON p.market_id = o.market_id AND p.sku = o.sku
LEFT JOIN ${catalog}.${schema}.competitor_prices c
  ON c.week_start = o.week_start AND c.market_id = o.market_id AND c.channel = o.channel AND c.competitor_sku = p.competitor_sku
LEFT JOIN ${catalog}.${schema}.sku_pnl s
  ON s.week_start = o.week_start AND s.market_id = o.market_id AND s.channel = o.channel AND s.sku = o.sku;

CREATE OR REPLACE VIEW ${catalog}.${schema}.pricing_kpis
WITH METRICS
LANGUAGE YAML
COMMENT 'Governed pricing metrics for Acme Beverages: volume, NSV, gross profit, GM%, average price and price index vs the competitive pair, by week, market, channel, brand, pack and SKU.'
AS $$
version: 1.1
source: ${catalog}.${schema}.v_price_position
joins:
  - name: product
    source: ${catalog}.${schema}.dim_product
    on: source.sku = product.sku
  - name: market
    source: ${catalog}.${schema}.dim_market
    on: source.market_id = market.market_id
dimensions:
  - name: week_start
    expr: source.week_start
    comment: Monday of the week.
  - name: market_id
    expr: source.market_id
  - name: market_name
    expr: market.market_name
  - name: region
    expr: market.region
  - name: channel
    expr: source.channel
  - name: retailer
    expr: source.retailer
  - name: brand
    expr: product.brand
  - name: category
    expr: product.category
  - name: pack_type
    expr: source.pack_type
  - name: sku
    expr: source.sku
  - name: product_name
    expr: product.product_name
  - name: competitor_brand
    expr: source.competitor_brand
  - name: on_promo
    expr: source.on_promo
measures:
  - name: volume_units
    expr: SUM(source.units)
    comment: Consumer units sold.
  - name: nsv_usd
    expr: SUM(source.nsv)
    comment: Net sales value to Acme in USD.
  - name: gp_usd
    expr: SUM(source.gp)
    comment: Gross profit in USD.
  - name: gm_pct
    expr: SUM(source.gp) / NULLIF(SUM(source.nsv), 0)
    comment: Gross margin as a fraction of NSV.
  - name: avg_price_usd
    expr: SUM(source.effective_price * source.units) / NULLIF(SUM(source.units), 0)
    comment: Volume-weighted average consumer price paid per unit (promo price when promoted).
  - name: price_index_vs_pair
    expr: 100 * SUM(source.shelf_price * source.units) / NULLIF(SUM(source.competitor_shelf_price * source.units), 0)
    comment: Volume-weighted shelf price index vs the pair competitor (100 = parity). Compare with the target band in price_index_vs_pairs.
$$
