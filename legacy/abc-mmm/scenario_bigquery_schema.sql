-- ABC MMM Scenario Planner — BigQuery schemas
-- Project : donut-426
-- Dataset : abc
--
-- Run this once to create the target tables. scenario_planner.py appends
-- run_id-partitioned rows, so Looker Studio always filters by the latest
-- run_id from scenario_metadata.

CREATE SCHEMA IF NOT EXISTS `donut-426.abc`;

-- ---------------------------------------------------------------
-- A. Fixed-budget reallocation at current total spend
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `donut-426.abc.scenario_reallocation` (
  run_id                           STRING    NOT NULL,
  run_uuid                         STRING    NOT NULL,
  fiscal_year                      STRING,
  plan_start                       DATE,
  plan_end                         DATE,
  scenario                         STRING,   -- 'reallocation'
  scenario_value                   FLOAT64,  -- total budget
  channel                          STRING,
  spend_baseline                   FLOAT64,
  spend_optimized                  FLOAT64,
  incremental_outcome_baseline     FLOAT64,
  incremental_outcome_optimized    FLOAT64,
  roi_baseline                     FLOAT64,
  roi_optimized                    FLOAT64,
  mroi_baseline                    FLOAT64,
  mroi_optimized                   FLOAT64,
  delta_spend                      FLOAT64,
  delta_revenue                    FLOAT64
)
PARTITION BY plan_start
CLUSTER BY run_id, channel;

-- ---------------------------------------------------------------
-- B. Budget-flex sweep (-30% .. +30% of current)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `donut-426.abc.scenario_budget_flex` (
  run_id                           STRING    NOT NULL,
  run_uuid                         STRING    NOT NULL,
  fiscal_year                      STRING,
  plan_start                       DATE,
  plan_end                         DATE,
  scenario                         STRING,   -- 'budget_flex'
  scenario_value                   FLOAT64,  -- same as budget_pct
  budget_pct                       FLOAT64,  -- e.g. 0.90 = 90% of current
  total_budget                     FLOAT64,
  channel                          STRING,
  spend_baseline                   FLOAT64,
  spend_optimized                  FLOAT64,
  incremental_outcome_baseline     FLOAT64,
  incremental_outcome_optimized    FLOAT64,
  roi_baseline                     FLOAT64,
  roi_optimized                    FLOAT64,
  mroi_baseline                    FLOAT64,
  mroi_optimized                   FLOAT64,
  delta_spend                      FLOAT64,
  delta_revenue                    FLOAT64
)
PARTITION BY plan_start
CLUSTER BY run_id, channel;

-- ---------------------------------------------------------------
-- C. Per-channel response curves
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `donut-426.abc.scenario_response_curves` (
  run_id                      STRING    NOT NULL,
  run_uuid                    STRING    NOT NULL,
  fiscal_year                 STRING,
  plan_start                  DATE,
  plan_end                    DATE,
  channel                     STRING,
  multiplier                  FLOAT64,  -- 0.0 .. 2.0
  spend                       FLOAT64,
  baseline_spend              FLOAT64,
  incremental_revenue         FLOAT64,
  incremental_revenue_lo      FLOAT64,
  incremental_revenue_hi      FLOAT64,
  roi                         FLOAT64,
  mroi                        FLOAT64
)
PARTITION BY plan_start
CLUSTER BY run_id, channel;

-- ---------------------------------------------------------------
-- D. Target-ROAS sweep
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `donut-426.abc.scenario_target_roas` (
  run_id                           STRING    NOT NULL,
  run_uuid                         STRING    NOT NULL,
  fiscal_year                      STRING,
  plan_start                       DATE,
  plan_end                         DATE,
  scenario                         STRING,   -- 'target_roas'
  scenario_value                   FLOAT64,  -- same as target_roas
  target_roas                      FLOAT64,
  required_budget                  FLOAT64,
  channel                          STRING,
  spend_baseline                   FLOAT64,
  spend_optimized                  FLOAT64,
  incremental_outcome_baseline     FLOAT64,
  incremental_outcome_optimized    FLOAT64,
  roi_baseline                     FLOAT64,
  roi_optimized                    FLOAT64,
  mroi_baseline                    FLOAT64,
  mroi_optimized                   FLOAT64,
  delta_spend                      FLOAT64,
  delta_revenue                    FLOAT64
)
PARTITION BY plan_start
CLUSTER BY run_id, channel;

-- ---------------------------------------------------------------
-- Metadata — one row per scenario export
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `donut-426.abc.scenario_metadata` (
  run_id            STRING   NOT NULL,
  run_uuid          STRING   NOT NULL,
  fiscal_year       STRING,
  plan_start        DATE,
  plan_end          DATE,
  baseline_budget   FLOAT64,
  media_channels    STRING,
  n_flex_points     INT64,
  n_curve_points    INT64,
  n_roas_targets    INT64,
  created_at_utc    TIMESTAMP
);

-- ---------------------------------------------------------------
-- Convenience views — Looker Studio points at these so dashboards always
-- reflect the latest run_id without manual re-binding.
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW `donut-426.abc.v_scenario_latest_run` AS
SELECT *
FROM `donut-426.abc.scenario_metadata`
QUALIFY ROW_NUMBER() OVER (ORDER BY created_at_utc DESC) = 1;

CREATE OR REPLACE VIEW `donut-426.abc.v_scenario_reallocation` AS
SELECT r.*
FROM `donut-426.abc.scenario_reallocation` r
JOIN `donut-426.abc.v_scenario_latest_run`  m USING (run_id);

CREATE OR REPLACE VIEW `donut-426.abc.v_scenario_budget_flex` AS
SELECT r.*
FROM `donut-426.abc.scenario_budget_flex`   r
JOIN `donut-426.abc.v_scenario_latest_run`  m USING (run_id);

CREATE OR REPLACE VIEW `donut-426.abc.v_scenario_response_curves` AS
SELECT r.*
FROM `donut-426.abc.scenario_response_curves` r
JOIN `donut-426.abc.v_scenario_latest_run`    m USING (run_id);

CREATE OR REPLACE VIEW `donut-426.abc.v_scenario_target_roas` AS
SELECT r.*
FROM `donut-426.abc.scenario_target_roas`   r
JOIN `donut-426.abc.v_scenario_latest_run`  m USING (run_id);
