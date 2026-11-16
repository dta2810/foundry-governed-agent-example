CREATE SCHEMA IF NOT EXISTS ${catalog}.${schema} COMMENT 'Acme Beverages commercial playbook & pricing (fictitious company, synthetic data).';
CREATE VOLUME IF NOT EXISTS ${catalog}.${schema}.${volume} COMMENT 'Landing files for the synthetic pricing data and the margin guardrail spreadsheet';
CREATE SCHEMA IF NOT EXISTS ${catalog}.${trace_schema} COMMENT 'Evidence: Unity Gateway policy decisions and traffic classification views.'
