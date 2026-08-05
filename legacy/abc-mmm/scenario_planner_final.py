# -*- coding: utf-8 -*-
"""
ABC MMM — Scenario planner export to BigQuery (consolidated)
------------------------------------------------------------
Run this cell after `mmm` is fit. It builds four scenarios and writes
them to `donut-426.abc.*`:

  A. Fixed-budget reallocation at current total spend
  B. Budget flex sweep (-30% .. +30% of current total, 5% steps)
  C. Per-channel response curves (0% .. 200%, 10% steps)
  D. Target-ROAS sweep

Each run gets a unique run_id; Looker Studio filters the latest via
`v_scenario_latest_run`. Re-running this cell appends a new run_id,
so history is preserved.
"""

import datetime
import inspect
import uuid

import numpy as np
import pandas as pd
import pandas_gbq

from meridian.analysis import analyzer as analyzer_module
from meridian.analysis import optimizer as budget_optimizer_module

# -------------------------------------------------------------------
# 0) Config
# -------------------------------------------------------------------
PROJECT_ID        = "donut-426"
DATASET           = "abc"
FISCAL_YEAR_LABEL = "FY26"
PLAN_START        = "2025-02-23"          # start of model's weekly data
PLAN_END          = "2026-02-15"          # end of model's weekly data
RUN_ID            = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
RUN_UUID          = str(uuid.uuid4())

FLEX_PCTS           = np.round(np.arange(0.70, 1.31, 0.05), 2).tolist()
CURVE_MULTIPLIERS   = np.round(np.arange(0.0, 2.01, 0.10), 2).tolist()
TARGET_ROAS_VALUES  = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]

print(f"run_id={RUN_ID}   plan={PLAN_START}..{PLAN_END}")

# -------------------------------------------------------------------
# 1) Baseline: current spend over the planning window
# -------------------------------------------------------------------
_mask = (df_bq["time"] >= PLAN_START) & (df_bq["time"] <= PLAN_END)
_plan_df = df_bq.loc[_mask]

baseline_spend_by_channel = {
    ch: float(_plan_df[f"{ch}_spend"].sum()) for ch in media_channels
}
baseline_total_budget = float(sum(baseline_spend_by_channel.values()))
print(f"Baseline total spend: ${baseline_total_budget:,.0f}")

analyzer          = analyzer_module.Analyzer(mmm)
budget_optimizer  = budget_optimizer_module.BudgetOptimizer(mmm)


def _results_to_channel_df(opt_results, scenario, scenario_value):
    """Normalize a Meridian OptimizationResults into a long channel-level frame."""
    opt  = opt_results.optimized_data.to_dataframe().reset_index()
    base = opt_results.nonoptimized_data.to_dataframe().reset_index()
    out = opt.merge(base, on="channel", suffixes=("_optimized", "_baseline"))
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
realloc    = budget_optimizer.optimize(
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
# Meridian's response_curves() signature has changed across versions, so
# introspect what kwargs it accepts and pass only those.
print("\n[C] Per-channel response curves ...")
_rc_sig_params = set(inspect.signature(analyzer.response_curves).parameters.keys())
_rc_kwargs = {"spend_multipliers": CURVE_MULTIPLIERS}
if "selected_times"    in _rc_sig_params: _rc_kwargs["selected_times"]    = (PLAN_START, PLAN_END)
if "use_posterior"     in _rc_sig_params: _rc_kwargs["use_posterior"]     = True
if "confidence_level"  in _rc_sig_params: _rc_kwargs["confidence_level"]  = 0.90

rc        = analyzer.response_curves(**_rc_kwargs)
curves_df = rc.to_dataframe().reset_index()

rename_map = {
    "spend_multiplier":     "multiplier",
    "roi_mean":             "roi",
    "mroi_mean":            "mroi",
}
curves_df = curves_df.rename(columns={k: v for k, v in rename_map.items() if k in curves_df.columns})

curves_df["run_id"]         = RUN_ID
curves_df["run_uuid"]       = RUN_UUID
curves_df["fiscal_year"]    = FISCAL_YEAR_LABEL
curves_df["plan_start"]     = PLAN_START
curves_df["plan_end"]       = PLAN_END
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
    f["required_budget"] = f["spend_optimized"].sum()
    target_frames.append(f)
target_df = pd.concat(target_frames, ignore_index=True) if target_frames else pd.DataFrame()

# -------------------------------------------------------------------
# 6) Metadata row
# -------------------------------------------------------------------
meta_df = pd.DataFrame([{
    "run_id":          RUN_ID,
    "run_uuid":        RUN_UUID,
    "fiscal_year":     FISCAL_YEAR_LABEL,
    "plan_start":      PLAN_START,
    "plan_end":        PLAN_END,
    "baseline_budget": baseline_total_budget,
    "media_channels":  ",".join(media_channels),
    "n_flex_points":   len(FLEX_PCTS),
    "n_curve_points":  len(CURVE_MULTIPLIERS),
    "n_roas_targets":  len(TARGET_ROAS_VALUES),
    "created_at_utc":  datetime.datetime.utcnow(),
}])

# -------------------------------------------------------------------
# 7) Reshape response-curves wide-form (Meridian returns long-form with
#    a "metric" column: mean/ci_lo/ci_hi). BigQuery table expects one
#    row per (channel, multiplier) with columns for each metric.
# -------------------------------------------------------------------
if "metric" in curves_df.columns:
    keep_cols = ["channel","multiplier","spend","run_id","run_uuid",
                 "fiscal_year","plan_start","plan_end","baseline_spend"]
    keep_cols = [c for c in keep_cols if c in curves_df.columns]
    idx_cols  = [c for c in keep_cols if c != "spend"]
    spend_df  = (curves_df[curves_df["metric"] == "mean"]
                 [idx_cols + ["spend"]].reset_index(drop=True))
    wide = curves_df.pivot_table(
        index=idx_cols, columns="metric",
        values="incremental_revenue", aggfunc="first",
    ).reset_index()
    wide = wide.rename(columns={
        "mean":  "incremental_revenue",
        "ci_lo": "incremental_revenue_lo",
        "ci_hi": "incremental_revenue_hi",
    })
    curves_df_bq = wide.merge(spend_df, on=idx_cols, how="left")
    for col in ["roi", "mroi"]:
        if col not in curves_df_bq.columns:
            curves_df_bq[col] = None
else:
    curves_df_bq = curves_df

# -------------------------------------------------------------------
# 8) Schema-filtered BigQuery push
# -------------------------------------------------------------------
SCHEMAS = {
    "scenario_reallocation": [
        "run_id","run_uuid","fiscal_year","plan_start","plan_end",
        "scenario","scenario_value","channel",
        "spend_baseline","spend_optimized",
        "incremental_outcome_baseline","incremental_outcome_optimized",
        "roi_baseline","roi_optimized","mroi_baseline","mroi_optimized",
        "delta_spend","delta_revenue",
    ],
    "scenario_budget_flex": [
        "run_id","run_uuid","fiscal_year","plan_start","plan_end",
        "scenario","scenario_value","budget_pct","total_budget","channel",
        "spend_baseline","spend_optimized",
        "incremental_outcome_baseline","incremental_outcome_optimized",
        "roi_baseline","roi_optimized","mroi_baseline","mroi_optimized",
        "delta_spend","delta_revenue",
    ],
    "scenario_response_curves": [
        "run_id","run_uuid","fiscal_year","plan_start","plan_end",
        "channel","multiplier","spend","baseline_spend",
        "incremental_revenue","incremental_revenue_lo","incremental_revenue_hi",
        "roi","mroi",
    ],
    "scenario_target_roas": [
        "run_id","run_uuid","fiscal_year","plan_start","plan_end",
        "scenario","scenario_value","target_roas","required_budget","channel",
        "spend_baseline","spend_optimized",
        "incremental_outcome_baseline","incremental_outcome_optimized",
        "roi_baseline","roi_optimized","mroi_baseline","mroi_optimized",
        "delta_spend","delta_revenue",
    ],
    "scenario_metadata": [
        "run_id","run_uuid","fiscal_year","plan_start","plan_end",
        "baseline_budget","media_channels","n_flex_points","n_curve_points",
        "n_roas_targets","created_at_utc",
    ],
}

def _push(df, table):
    cols    = SCHEMAS[table]
    missing = [c for c in cols      if c not in df.columns]
    extra   = [c for c in df.columns if c not in cols]
    if missing:
        print(f"   WARN {table}: missing cols {missing} (will be NULL)")
        for c in missing:
            df = df.assign(**{c: None})
    if extra:
        print(f"   (dropping extra cols: {extra})")
    df = df[cols]
    fq = f"{DATASET}.{table}"
    print(f"   → {PROJECT_ID}.{fq}  ({len(df):,} rows, {len(df.columns)} cols)")
    pandas_gbq.to_gbq(
        df, fq,
        project_id=PROJECT_ID,
        if_exists="append",     # keeps history; Looker filters latest run_id
    )

print("\nWriting tables to BigQuery ...")
_push(realloc_df,    "scenario_reallocation")
_push(flex_df,       "scenario_budget_flex")
_push(curves_df_bq,  "scenario_response_curves")
if not target_df.empty:
    _push(target_df, "scenario_target_roas")
_push(meta_df,       "scenario_metadata")

print(f"\n✅ Scenario planner export complete. run_id={RUN_ID}")
