# ABC MMM Scenario Planner — Looker Studio Setup Guide

This dashboard is driven by four BigQuery views produced by `scenario_planner.py`. The views always return rows for the latest `run_id`, so the dashboard refreshes as soon as you re-run the Colab export.

**Project / dataset:** `donut-426.abc`
**Data sources (views):**

- `v_scenario_reallocation` — fixed-budget reallocation at current total
- `v_scenario_budget_flex` — budget sweep, -30% to +30%
- `v_scenario_response_curves` — per-channel response curves
- `v_scenario_target_roas` — required budget per ROAS target
- `v_scenario_latest_run` — metadata (shown in header as "Last refreshed")

The dashboard has five pages. Build them in order — later pages reuse the calc fields and parameters from earlier ones.

---

## One-time setup

1. In Looker Studio, **Create → Data source → BigQuery → donut-426 → abc**, and add each of the five views above as a separate data source. Name them to match the view name so charts are easy to wire up.
2. For every data source, set the **Date range dimension** to `plan_start` and mark `channel` as Text, `multiplier` / `budget_pct` / `target_roas` as Number.
3. Blend is not required — each page binds to exactly one source.

### Parameters — where and how to create them (updated)

In Looker Studio, classic **Parameters** are **data-source scoped**, not report-level. The "Resource → Manage variables (parameters)" menu item now opens a different BETA feature — don't use that. Instead, create each parameter on the specific data source(s) where it's used:

1. Click **Data** in the right rail, then click the data source name (or click the pencil next to it) to open the data source editor.
2. In the data source editor, click **+ Add a parameter** in the top toolbar (or from the Data panel, click the **+ Add a parameter** link at the bottom of the field list — faster).
3. Fill out the dialog exactly as described in the recipe below. For "List of values", click **+ Add another value** for each entry; Looker auto-fills the Label from the Value, which is fine.

#### Parameter recipe (copy/paste)

Create each of these four parameters on the data source(s) listed under "Where". Parameter IDs are auto-generated — use the suggested ID override if the auto-gen is ugly.

| Parameter name         | Where (data source)                                    | Data type          | Permitted values | Values (one row per entry)                                                                                                   | Default |
|------------------------|--------------------------------------------------------|--------------------|------------------|------------------------------------------------------------------------------------------------------------------------------|---------|
| `p_budget_pct`         | `v_scenario_budget_flex`                                | Number (decimal)   | List of values   | 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30                                                 | 1.00    |
| `p_target_roas`        | `v_scenario_target_roas`                                | Number (decimal)   | List of values   | 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0                                                                                       | 3.0     |
| `p_channel`            | `v_scenario_response_curves`                            | Text               | List of values   | Meta, Search, PMAX, Amex, Video_Epsilon, Video_Google, Video_Hulu, Video_MNTN, Video_Paramount                               | Meta    |
| `p_channel_multiplier` | `v_scenario_response_curves`                            | Number (decimal)   | List of values   | 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0                      | 1.0     |

> **Tip** — for the two long lists (`p_budget_pct` and `p_channel_multiplier`), each "Add another value" click creates a blank row with the cursor in the Value field. Type the value, press Tab to jump to Label (auto-filled — just press Tab again), then click "Add another value" for the next. ~90 seconds per parameter.

> **Why not Range?** Looker's "Range" parameter type is a single slider, not a stepped list. Our scenarios are discrete values (0.70, 0.75, …) so "List of values" is required.

### Report-level calculated fields

Add these on each data source via **Data panel → + Add a field** at the bottom of the field list (faster than opening the data source editor):

| Field                      | Formula                                                 | Where    | Notes                                                                                                       |
|----------------------------|----------------------------------------------------------|----------|-------------------------------------------------------------------------------------------------------------|
| `ROAS_optimized`           | `incremental_outcome_optimized / spend_optimized`       | A, B, D  | Row-level ratio. ✅ works at source level.                                                                  |
| `ROAS_baseline`            | `incremental_outcome_baseline / spend_baseline`         | A, B, D  | Row-level ratio. ✅ works at source level.                                                                  |
| `ROAS`                     | `incremental_revenue / spend`                           | C        | Row-level ratio on response curves. ✅ works at source level.                                               |
| `is_selected_mult`         | `CASE WHEN multiplier = p_channel_multiplier THEN 1 ELSE 0 END` | C | Depends on `p_channel_multiplier` — add this field **after** the parameter exists.                         |
| `is_baseline_point`        | `CASE WHEN multiplier = 1.0 THEN 1 ELSE 0 END`          | C        | Single-point marker for the "you are here" overlay.                                                         |
| `spend_mix_pct`            | _see note below_                                         | A, B, D  | ⚠️ **Do not add as a source-level calc** — Looker rejects mixing aggregated `SUM(...)` with a raw dimension. |
| `baseline_mix_pct`         | _see note below_                                         | A, B, D  | ⚠️ Same issue. Use chart-level comparison instead.                                                          |

(A = v_scenario_reallocation · B = v_scenario_budget_flex · C = v_scenario_response_curves · D = v_scenario_target_roas)

#### Mix-pct workaround (chart-level, not source-level)

Do this directly on any 100%-stacked or table chart where you want a share-of-spend column:

1. Drop `spend_optimized` (or `spend_baseline`) into the chart as a metric.
2. On the metric pill, click the small pencil / down-arrow → **Comparison calculation** → **Percent of total**.
3. The chart now renders the metric as "% of total spend" for its current breakdown (typically `channel`).

No calc field needed — and you get correct aggregation automatically.

#### Scaffolded so far

Claude has already created these calc fields on your data sources:

- `v_scenario_budget_flex`: `ROAS_optimized` ✅, `ROAS_baseline` ✅
- `v_scenario_reallocation`: `ROAS_optimized` ✅, `ROAS_baseline` ✅
- `v_scenario_target_roas`: `ROAS_optimized` ✅, `ROAS_baseline` ✅
- `v_scenario_response_curves`: `ROAS` ✅, `is_baseline_point` ✅

Remaining — add manually after the matching parameter exists:
- `v_scenario_response_curves`: `is_selected_mult` — requires `p_channel_multiplier`. Formula: `CASE WHEN multiplier = p_channel_multiplier THEN 1 ELSE 0 END`

---

## Page 1 — Overview

**Source:** `v_scenario_latest_run` + `v_scenario_reallocation`

| Element                      | Chart type       | Config                                                                                     |
|------------------------------|------------------|--------------------------------------------------------------------------------------------|
| Header                       | Text             | "ABC MMM Scenario Planner — FY26"                                                          |
| Last refreshed               | Scorecard        | metric `created_at_utc` (Max), source `v_scenario_latest_run`                              |
| Baseline total budget        | Scorecard        | `baseline_budget` from `v_scenario_latest_run`, $ format                                   |
| Baseline incremental revenue | Scorecard        | `SUM(incremental_outcome_baseline)` from reallocation                                      |
| Optimized incremental revenue| Scorecard        | `SUM(incremental_outcome_optimized)`                                                       |
| Uplift %                     | Scorecard        | `(SUM(incremental_outcome_optimized) - SUM(incremental_outcome_baseline)) / SUM(incremental_outcome_baseline)` |
| Channel mix — current vs. optimized | 100% stacked bar | dimension `run_id`, breakdown `channel`, series metrics `spend_baseline` and `spend_optimized` (or two bars side-by-side) |
| Callout text                 | Text             | "Fixed-budget reallocation at current total spend"                                         |

## Page 2 — Fixed-budget reallocation

**Source:** `v_scenario_reallocation`

1. **Spend reallocation waterfall** — Bar chart, dimension `channel`, metric `delta_spend`. Conditional formatting: green > 0, red < 0.
2. **Revenue impact by channel** — Bar chart, dimension `channel`, metric `delta_revenue`, sorted descending.
3. **Side-by-side spend table** — Table with `channel`, `spend_baseline`, `spend_optimized`, `delta_spend`, `ROAS_baseline`, `ROAS_optimized`, `delta_revenue`. Heatmap on `delta_revenue`.
4. **Marginal ROAS at optimum** — Bar chart, dimension `channel`, metric `mroi_optimized`. Reference line at 1.0.

## Page 3 — Budget flex (-30% .. +30%)

**Source:** `v_scenario_budget_flex`

1. **Budget dropdown** — Control filter on `budget_pct`, tied to `p_budget_pct`.
2. **Total revenue curve** — Line chart, dimension `budget_pct`, metric `SUM(incremental_outcome_optimized)`. Second line: `SUM(spend_optimized)`. Shows diminishing returns.
3. **Total ROAS curve** — Line chart, dimension `budget_pct`, metric `SUM(incremental_outcome_optimized) / SUM(spend_optimized)`.
4. **Channel mix by budget level** — 100% stacked area, dimension `budget_pct`, breakdown `channel`, metric `spend_optimized`.
5. **Selected budget detail** — Table filtered by `budget_pct = p_budget_pct`, columns `channel`, `spend_optimized`, `incremental_outcome_optimized`, `ROAS_optimized`, `mroi_optimized`. This is the "what if we budget X" view.

## Page 4 — Channel what-if (response curves)

**Source:** `v_scenario_response_curves`

1. **Channel dropdown** — Control filter on `channel`, tied to `p_channel`.
2. **Multiplier slider** — Control filter on `multiplier`, tied to `p_channel_multiplier`.
3. **Response curve (spend vs. revenue)** — Line chart, filter to `channel = p_channel`, dimension `spend` (X), metric `incremental_revenue` (Y). Add confidence band using `incremental_revenue_lo` / `incremental_revenue_hi` as extra series.
4. **"You are here" marker** — Scatter overlay on same chart, filtered by `is_baseline_point = 1`, a single point at current spend.
5. **Selected point scorecards** (all filtered by `multiplier = p_channel_multiplier` AND `channel = p_channel`):
    - `spend`
    - `incremental_revenue`
    - `ROAS`
    - `mroi`
6. **Channel comparison panel** — Small-multiples line chart (one tile per channel), dimension `multiplier`, metric `ROAS`, reference line at ROAS = 1.0. Helps compare saturation across channels.

## Page 5 — Target ROAS

**Source:** `v_scenario_target_roas`

1. **Target ROAS dropdown** — Control filter on `target_roas`, tied to `p_target_roas`.
2. **Required budget vs. target** — Line chart, dimension `target_roas`, metric `MAX(required_budget)`. Shows the spend ceiling as you raise the ROAS bar.
3. **Channel mix at selected target** — Pie chart filtered to `target_roas = p_target_roas`, dimension `channel`, metric `spend_optimized`.
4. **Detail table** filtered to `target_roas = p_target_roas`: `channel`, `spend_optimized`, `incremental_outcome_optimized`, `ROAS_optimized`, `mroi_optimized`.
5. **Callout** — "To hit ROAS of {p_target_roas}, spend {required_budget} — reducing total by {$baseline - required_budget}."

---

## Refresh & sharing

- Looker Studio's BigQuery connector caches for ~12 hours by default. Set **File → Report settings → Data freshness** to 1 hour (or manually hit "Refresh data") after each Colab run.
- Share the report view-only with the marketing team. They can change parameters without editing the report.

## When to re-run the exporter

Re-run `scenario_planner.py` when any of the following happen:

- `mmm` is re-fit against new weekly data
- Priors, adstock, or channel list change
- You want a new fiscal-year window — change `PLAN_START` / `PLAN_END` / `FISCAL_YEAR_LABEL` at the top of the script

Every run appends a new `run_id` to the raw tables; the `v_scenario_*` views always show only the latest run, so the dashboard updates automatically.
