# ABC MMM Scenario Planner — Package README

Three files in this folder make up the scenario planner:

| File                              | What it is                                                                 |
|-----------------------------------|------------------------------------------------------------------------------|
| `scenario_bigquery_schema.sql`    | One-time DDL: creates the five scenario tables + five "latest run" views in `donut-426.abc`. |
| `scenario_planner.py`             | Drop-in Colab cell. Requires the fitted `mmm` model from `mmmv10.py` already in memory. Runs all four scenarios and appends rows to BigQuery. |
| `looker_studio_setup.md`          | Step-by-step build guide for the five-page Looker Studio report that binds to those views. |

## Run order (first time)

1. **BigQuery:** open the SQL console in the `donut-426` project and run `scenario_bigquery_schema.sql`. This creates the tables and the latest-run views.
2. **Colab:** run your existing `mmmv10.py` through to the end so `mmm`, `df_bq`, and `media_channels` are in memory.
3. **Colab:** paste the contents of `scenario_planner.py` into a new cell and run it. Expect a few minutes — each budget-flex and target-ROAS point is a full optimizer pass.
4. **Looker Studio:** follow `looker_studio_setup.md` to build the report. After the first build, subsequent refreshes are just step 3 again.

## Scenarios produced

| Table                           | Scenario                                                      | Granularity                |
|---------------------------------|----------------------------------------------------------------|----------------------------|
| `scenario_reallocation`         | Optimal mix at current total budget                            | 1 row per channel          |
| `scenario_budget_flex`          | Optimal mix at 70 %, 75 %, … 130 % of current total            | 13 budget pts × 9 channels |
| `scenario_response_curves`      | Per-channel response curves, 0 %–200 % of baseline in 10 % steps | 21 pts × 9 channels       |
| `scenario_target_roas`          | Required budget + mix for ROAS targets 1.5 × through 6 ×       | 8 targets × 9 channels     |
| `scenario_metadata`             | One row per export run                                          | 1 row                      |

## Caveats / things I'd check after the first run

- **Meridian API names for `response_curves`.** I used `analyzer.response_curves(spend_multipliers=..., selected_times=...)` and a rename map for the common output columns (`mean`, `ci_lo`, `ci_hi`, `roi_mean`, `mroi_mean`). Newer Meridian versions have shuffled these once or twice; if the resulting DataFrame has different column names, adjust `rename_map` in `scenario_planner.py` and re-run.
- **Optimization runtime.** Each `budget_optimizer.optimize()` call is expensive because it ranges over the full 52-week plan window with 20 chains × 3000 draws. The flex + target-ROAS loops together do ~21 optimizer runs. On a GPU-backed Colab that's ~10–20 minutes total; on CPU, expect an hour. If that's painful, drop `FLEX_PCTS` to 5% intervals or shorten `PLAN_END`.
- **Target-ROAS infeasibility.** Some targets (especially >5x) may be infeasible given the fitted response curves; the script catches and skips those rather than failing. Check the console output.
- **Meridian's `optimize()` requires dates inside the model's input.** "Full fiscal year" here = the last 52 model weeks, used as the analog for next year's plan. If ABC's fiscal year is not Feb-to-Feb, change `PLAN_START` / `PLAN_END` / `FISCAL_YEAR_LABEL` at the top of `scenario_planner.py`.
- **`if_exists="append"`** — the script appends to each table and the Looker views filter to the latest `run_id`. If you want to prune old runs, periodically `DELETE FROM ... WHERE run_id NOT IN (SELECT run_id FROM v_scenario_latest_run)`.
