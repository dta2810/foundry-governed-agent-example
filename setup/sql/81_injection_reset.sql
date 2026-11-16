-- Reset the injection scene (80_injection_scene.sql) to the original competitor brand.
UPDATE ${catalog}.${schema}.competitor_pairs
SET competitor_brand = 'Northwind Fizz'
WHERE pair_id = 'CP-015'
