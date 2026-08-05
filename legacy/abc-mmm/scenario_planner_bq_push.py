# Final step — define _push and write the computed DataFrames to BigQuery.
import pandas_gbq

PROJECT_ID = "donut-426"
DATASET    = "abc"

def _push(df, table):
    fq = f"{DATASET}.{table}"
    print(f"   → {PROJECT_ID}.{fq}  ({len(df):,} rows, {len(df.columns)} cols)")
    pandas_gbq.to_gbq(
        df, fq,
        project_id=PROJECT_ID,
        if_exists="append",
    )

# -------------------------------------------------------------------
# Align curves_df to BQ schema: pivot metric column into wide form
# -------------------------------------------------------------------
print(f"curves_df raw: rows={len(curves_df):,} cols={list(curves_df.columns)}")
if "metric" in curves_df.columns:
    print(f"  metric values: {curves_df['metric'].unique().tolist()}")
    # Pivot metric into columns: mean → incremental_revenue,
    # ci_lo → incremental_revenue_lo, ci_hi → incremental_revenue_hi
    keep_cols = ["channel", "multiplier", "spend", "run_id", "run_uuid",
                 "fiscal_year", "plan_start", "plan_end", "baseline_spend"]
    keep_cols = [c for c in keep_cols if c in curves_df.columns]
    idx_cols  = [c for c in keep_cols if c != "spend"]  # spend is a per-metric value we want once
    # Take one row per (channel, multiplier) for spend (spend is same across metrics)
    spend_df  = curves_df[curves_df["metric"] == "mean"][idx_cols + ["spend"]].reset_index(drop=True)
    # Pivot the revenue metric across metric values
    wide = curves_df.pivot_table(
        index=idx_cols,
        columns="metric",
        values="incremental_revenue",
        aggfunc="first",
    ).reset_index()
    wide = wide.rename(columns={
        "mean":  "incremental_revenue",
        "ci_lo": "incremental_revenue_lo",
        "ci_hi": "incremental_revenue_hi",
    })
    curves_wide = wide.merge(spend_df, on=idx_cols, how="left")
    # Add missing columns so BQ schema matches (roi, mroi can be NULL)
    for col in ["roi", "mroi"]:
        if col not in curves_wide.columns:
            curves_wide[col] = None
    # Cast plan_start/plan_end to date strings (already strings)
    curves_df_bq = curves_wide
else:
    curves_df_bq = curves_df
print(f"curves_df_bq: rows={len(curves_df_bq):,} cols={list(curves_df_bq.columns)}")

# -------------------------------------------------------------------
# Write to BigQuery
# -------------------------------------------------------------------
print("\nWriting tables to BigQuery ...")
_push(realloc_df,    "scenario_reallocation")
_push(flex_df,       "scenario_budget_flex")
_push(curves_df_bq,  "scenario_response_curves")
if not target_df.empty:
    _push(target_df, "scenario_target_roas")
_push(meta_df,       "scenario_metadata")
print(f"\n✅ Scenario planner export complete. run_id={RUN_ID}")
