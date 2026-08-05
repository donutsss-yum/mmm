# -*- coding: utf-8 -*-
"""
ABC MMM — Scenario Planner export to BigQuery
---------------------------------------------
Drop this cell into the same Colab notebook that fits `mmm` (mmmv10.py).
It assumes `mmm`, `df_bq`, `media_channels`, and `media_spend_cols` are in
the global namespace, and that `pandas_gbq` + BigQuery auth are already set up.

What it does:
  A. Fixed-budget reallocation (optimal mix at *current* total spend)
  B. Budget-flex sweep (-30% to +30% of current total, 5% steps)
  C. Per-channel response curves (0% to 200% of channel baseline, 10% steps)
  D. Target-ROAS sweep (required budget + mix for a range of ROAS targets)

Writes four tables to `donut-426.abc.*`:
  - scenario_reallocation
  - scenario_budget_flex
  - scenario_response_curves
  - scenario_target_roas
  + a scenario_metadata row per run so Looker Studio can show "last refreshed".

Planning window: last 52 model weeks (the Meridian optimizer requires dates
inside the model's input data, so we use the full trailing year as the
analog for "next fiscal year"). Change `PLAN_START` / `PLAN_END` below if you
want a different horizon.
"""

import datetime
import uuid

import numpy as np
import pandas as pd
import pandas_gbq

from meridian.analysis import analyzer as analyzer_module
from meridian.analysis import optimizer as budget_optimizer_module

# -------------------------------------------------------------------
# 0) Config
# -------------------------------------------------------------------
PROJECT_ID = "donut-426"
DATASET    = "abc"
FISCAL_YEAR_LABEL = "FY26"                # shows up as a dimension in Looker
PLAN_START = "2025-02-23"                 # start of model's weekly data
PLAN_END   = "2026-02-15"                 # end of model's weekly data
RUN_ID     = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
RUN_UUID   = str(uuid.uuid4())

# Budget-flex sweep: -30% .. +30% of current total, 5% steps
FLEX_PCTS = np.round(np.arange(0.70, 1.31, 0.05), 2).tolist()

# Per-channel response curves: 0% .. 200% of baseline per channel, 10% steps
CURVE_MULTIPLIERS = np.round(np.arange(0.0, 2.01, 0.10), 2).tolist()

# Target ROAS sweep
TARGET_ROAS_VALUES = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]

# -------------------------------------------------------------------
# 1) Baseline: current spend over the planning window
# -------------------------------------------------------------------
_mask = (df_bq["time"] >= PLAN_START) & (df_bq["time"] <= PLAN_END)
_plan_df = df_bq.loc[_mask]

baseline_spend_by_channel = {
    ch: float(_plan_df[f"{ch}_spend"].sum()) for ch in media_channels
}
baseline_total_budget = float(sum(baseline_spend_by_channel.values()))
print(f"Baseline total spend {PLAN_START}..{PLAN_END}: ${baseline_total_budget:,.0f}")

analyzer = analyzer_module.Analyzer(mmm)
budget_optimizer = budget_optimizer_module.BudgetOptimizer(mmm)


def _results_to_channel_df(opt_results, scenario, scenario_value):
    """Normalize a Meridian OptimizationResults into a long channel-level frame."""
    opt  = opt_results.optimized_data.to_dataframe().reset_index()
    base = opt_results.nonoptimized_data.to_dataframe().reset_index()
    # expected columns: channel, spend, incremental_outcome, roi, mroi
    out = opt.merge(
        base,
        on="channel",
        suffixes=("_optimized", "_baseline"),
    )
    out["scenario"]       = scenario
    out["scenario_value"] = float(scenario_value)
    out["run_id"]         = RUN_ID
    out["run_uuid"]       = RUN_UUID
    out["fiscal_year"]    = FISCAL_YEAR_LABEL
    out["plan_start"]     = PLAN_START
    out["plan_end"]       = PLAN_END
    out["delta_spend"]    = out["spend_optimized"]               - out["spend_baseline"]
    out["delta_revenue"]  = out["incremental_outcome_optimized"] - out["incremental_outcome_baseline"]
    return out


# -------------------------------------------------------------------
# 2) Scenario A — Fixed-budget reallocation at current total spend
# -------------------------------------------------------------------
print("\n[A] Fixed-budget reallocation at current total ...")
realloc = budget_optimizer.optimize(
    fixed_budget=True,
    budget=baseline_total_budget,
    start_date=PLAN_START,
    end_date=PLAN_END,
)
realloc_df = _results_to_channel_df(realloc, "reallocation", baseline_total_budget)

# -------------------------------------------------------------------
# 3) Scenario B — Budget flex sweep
# -------------------------------------------------------------------
print("\n[B] Budget-flex sweep ...")
flex_frames = []
for pct in FLEX_PCTS:
    b = baseline_total_budget * pct
    print(f"   budget pct={pct:.2f}  total=${b:,.0f}")
    r = budget_optimizer.optimize(
        fixed_budget=True,
        budget=b,
        start_date=PLAN_START,
        end_date=PLAN_END,
    )
    f = _results_to_channel_df(r, "budget_flex", pct)
    f["budget_pct"]   = pct
    f["total_budget"] = b
    flex_frames.append(f)
flex_df = pd.concat(flex_frames, ignore_index=True)

# -------------------------------------------------------------------
# 4) Scenario C — Per-channel response curves
# -------------------------------------------------------------------
print("\n[C] Per-channel response curves ...")
# Meridian's analyzer has a native response-curves helper that sweeps each
# channel's spend by a multiplier while holding others constant.
rc = analyzer.response_curves(
    spend_multipliers=CURVE_MULTIPLIERS,
    selected_times=(PLAN_START, PLAN_END),
    by_reach_and_frequency=False,
    use_posterior=True,
    confidence_level=0.90,
)
curves_df = rc.to_dataframe().reset_index()
# Typical columns: channel, spend_multiplier, spend, mean (incremental_outcome),
#                  ci_lo, ci_hi, roi_mean, mroi_mean  (exact names vary by version)
# Normalize to a predictable schema:
rename_map = {
    "mean":                 "incremental_revenue",
    "incremental_outcome":  "incremental_revenue",
    "ci_lo":                "incremental_revenue_lo",
    "ci_hi":                "incremental_revenue_hi",
    "roi_mean":             "roi",
    "mroi_mean":            "mroi",
    "roi":                  "roi",
    "mroi":                 "mroi",
    "spend_multiplier":     "multiplier",
}
curves_df = curves_df.rename(columns={k: v for k, v in rename_map.items() if k in curves_df.columns})

curves_df["run_id"]      = RUN_ID
curves_df["run_uuid"]    = RUN_UUID
curves_df["fiscal_year"] = FISCAL_YEAR_LABEL
curves_df["plan_start"]  = PLAN_START
curves_df["plan_end"]    = PLAN_END
# Baseline reference for each channel so Looker can snap a "you-are-here" marker
curves_df["baseline_spend"] = curves_df["channel"].map(baseline_spend_by_channel)

# -------------------------------------------------------------------
# 5) Scenario D — Target-ROAS sweep
# -------------------------------------------------------------------
print("\n[D] Target-ROAS sweep ...")
target_frames = []
for t in TARGET_ROAS_VALUES:
    print(f"   target_roi={t}")
    try:
        r = budget_optimizer.optimize(
            fixed_budget=False,
            target_roi=t,
            start_date=PLAN_START,
            end_date=PLAN_END,
        )
    except Exception as e:
        print(f"     skipped target_roi={t}: {e}")
        continue
    f = _results_to_channel_df(r, "target_roas", t)
    f["target_roas"]     = t
    f["required_budget"] = f["spend_optimized"].sum()  # channel-sum per run
    target_frames.append(f)
target_df = pd.concat(target_frames, ignore_index=True) if target_frames else pd.DataFrame()

# -------------------------------------------------------------------
# 6) Metadata row
# -------------------------------------------------------------------
meta_df = pd.DataFrame([{
    "run_id":            RUN_ID,
    "run_uuid":          RUN_UUID,
    "fiscal_year":       FISCAL_YEAR_LABEL,
    "plan_start":        PLAN_START,
    "plan_end":          PLAN_END,
    "baseline_budget":   baseline_total_budget,
    "media_channels":    ",".join(media_channels),
    "n_flex_points":     len(FLEX_PCTS),
    "n_curve_points":    len(CURVE_MULTIPLIERS),
    "n_roas_targets":    len(TARGET_ROAS_VALUES),
    "created_at_utc":    datetime.datetime.utcnow(),
}])

# -------------------------------------------------------------------
# 7) Write everything to BigQuery
# -------------------------------------------------------------------
def _push(df, table):
    fq = f"{DATASET}.{table}"
    print(f"   → {PROJECT_ID}.{fq}  ({len(df):,} rows)")
    pandas_gbq.to_gbq(
        df, fq,
        project_id=PROJECT_ID,
        if_exists="append",          # keeps history; Looker filters latest run_id
    )

print("\nWriting tables to BigQuery ...")
_push(realloc_df, "scenario_reallocation")
_push(flex_df,    "scenario_budget_flex")
_push(curves_df,  "scenario_response_curves")
if not target_df.empty:
    _push(target_df, "scenario_target_roas")
_push(meta_df,    "scenario_metadata")

print(f"\n✅ Scenario planner export complete. run_id={RUN_ID}")
