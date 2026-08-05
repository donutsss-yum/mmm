# -*- coding: utf-8 -*-
"""
Continuation cell — picks up after the main scenario_planner.py cell crashed
at Scenario C because Analyzer.response_curves() no longer accepts
`by_reach_and_frequency`. Reuses realloc_df and flex_df already in memory,
rebuilds curves with the corrected API, runs the target-ROAS sweep, and
writes everything to BigQuery.

Requires the previous cell to have run through [B] (budget-flex sweep) so
that `realloc_df`, `flex_df`, `baseline_spend_by_channel`, `baseline_total_budget`,
`RUN_ID`, `RUN_UUID`, `FISCAL_YEAR_LABEL`, `PLAN_START`, `PLAN_END`,
`budget_optimizer`, `analyzer`, `TARGET_ROAS_VALUES`, `CURVE_MULTIPLIERS`,
`_results_to_channel_df`, and `_push` are in the kernel.
"""

import inspect
import datetime
import numpy as np
import pandas as pd
import pandas_gbq

# -------------------------------------------------------------------
# 0) Verify prerequisites
# -------------------------------------------------------------------
assert 'realloc_df' in dir(),  "realloc_df missing — re-run the main cell through [A]"
assert 'flex_df'    in dir(),  "flex_df missing — re-run the main cell through [B]"
print(f"Resuming with RUN_ID={RUN_ID}")
print(f"  realloc_df rows: {len(realloc_df):,}")
print(f"  flex_df    rows: {len(flex_df):,}")

# -------------------------------------------------------------------
# 1) Inspect analyzer.response_curves signature and call it correctly
# -------------------------------------------------------------------
sig = inspect.signature(analyzer.response_curves)
rc_params = set(sig.parameters.keys())
print(f"\nanalyzer.response_curves params: {sorted(rc_params)}")

rc_kwargs = {"spend_multipliers": CURVE_MULTIPLIERS}
if "selected_times" in rc_params:
    rc_kwargs["selected_times"] = (PLAN_START, PLAN_END)
if "use_posterior" in rc_params:
    rc_kwargs["use_posterior"] = True
if "confidence_level" in rc_params:
    rc_kwargs["confidence_level"] = 0.90

print(f"[C] Per-channel response curves ... kwargs={list(rc_kwargs.keys())}")
rc = analyzer.response_curves(**rc_kwargs)
curves_df = rc.to_dataframe().reset_index() if hasattr(rc, "to_dataframe") else pd.DataFrame(rc)

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
curves_df["baseline_spend"] = curves_df["channel"].map(baseline_spend_by_channel)
print(f"   curves_df rows={len(curves_df):,}  cols={list(curves_df.columns)}")

# -------------------------------------------------------------------
# 2) Scenario D — Target-ROAS sweep
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
print(f"   target_df rows={len(target_df):,}")

# -------------------------------------------------------------------
# 3) Metadata
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
# 4) Write to BigQuery
# -------------------------------------------------------------------
print("\nWriting tables to BigQuery ...")
_push(realloc_df, "scenario_reallocation")
_push(flex_df,    "scenario_budget_flex")
_push(curves_df,  "scenario_response_curves")
if not target_df.empty:
    _push(target_df, "scenario_target_roas")
_push(meta_df,    "scenario_metadata")

print(f"\n✅ Scenario planner export complete. run_id={RUN_ID}")
