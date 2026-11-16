-- market access seed: admin group + deployer see ALL; east/west groups see four markets each (rerun = reset)
DELETE FROM ${catalog}.${schema}.user_market_access WHERE note LIKE 'seed:%';
INSERT INTO ${catalog}.${schema}.user_market_access (principal, market_id, note) VALUES
  ('${group_admin}', 'ALL', 'seed: pricing admin group'),
  ('${group_east}', 'NY', 'seed: east analysts'), ('${group_east}', 'GA', 'seed: east analysts'),
  ('${group_east}', 'FL', 'seed: east analysts'), ('${group_east}', 'NC', 'seed: east analysts'),
  ('${group_west}', 'CA', 'seed: west analysts'), ('${group_west}', 'TX', 'seed: west analysts'),
  ('${group_west}', 'AZ', 'seed: west analysts'), ('${group_west}', 'IL', 'seed: west analysts');
INSERT INTO ${catalog}.${schema}.user_market_access (principal, market_id, note) SELECT current_user(), 'ALL', 'seed: deployer';

CREATE OR REPLACE FUNCTION ${catalog}.${schema}.rf_market_access(p_market_id STRING)
RETURNS BOOLEAN
COMMENT 'Row filter on market_id: true when the caller (current_user) or one of its account groups is mapped to the market (or ALL) in user_market_access, or is in the pricing admin group.'
RETURN is_account_group_member('${group_admin}')
  OR EXISTS (SELECT 1 FROM ${catalog}.${schema}.user_market_access a
             WHERE a.market_id IN ('ALL', p_market_id)
               AND (a.principal = current_user() OR is_account_group_member(a.principal)));

ALTER TABLE ${catalog}.${schema}.price_observations SET ROW FILTER ${catalog}.${schema}.rf_market_access ON (market_id);
ALTER TABLE ${catalog}.${schema}.competitor_prices SET ROW FILTER ${catalog}.${schema}.rf_market_access ON (market_id);
ALTER TABLE ${catalog}.${schema}.competitor_pairs SET ROW FILTER ${catalog}.${schema}.rf_market_access ON (market_id);
ALTER TABLE ${catalog}.${schema}.promo_events SET ROW FILTER ${catalog}.${schema}.rf_market_access ON (market_id);
ALTER TABLE ${catalog}.${schema}.sku_pnl SET ROW FILTER ${catalog}.${schema}.rf_market_access ON (market_id)
