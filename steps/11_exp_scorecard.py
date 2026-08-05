# @title Step 11 - EXPERIMENT v14-revenue-split: scorecard (holdout accuracy + double-count check)
# =============================================================================
# Scores the split-model experiment against the refit baseline. Three questions:
#
# 1. HOLDOUT ACCURACY (the headline): on the last HOLDOUT_WEEKS weeks - which
#    none of the models saw in their KPI likelihood - does the summed prediction
#    pred(InStore) + pred(Digital) track ACTUAL TOTAL revenue better than the
#    baseline's pred(Total)? Metrics: R^2, MAPE, wMAPE. Train-window metrics are
#    reported too, but the split side has ~2x parameters, so IN-SAMPLE WINS ARE
#    EXPECTED AND MEANINGLESS - only the holdout comparison counts.
#
# 2. DOUBLE-COUNTING CHECK: per channel, full-window incremental revenue from
#    the baseline vs (InStore-model + Digital-model). Independent baselines let
#    both sub-models claim the same demand - ratios >> 1 mean the split
#    attribution is inflated and can't be trusted even if fit looks good.
#    Flag threshold: ratio outside [0.8, 1.25].
#
# 3. CONVERGENCE: max r_hat per model (roi_m / beta_m / ec_m) must be < 1.05,
#    else that model's numbers are noise regardless of the above.
#
# Also prints per-sub-model holdout accuracy on their OWN KPIs (diagnostic:
# e.g. does the Digital model track digital revenue at all?).
#
# Outputs: printed verdict + two stamped CSVs in <out_dir>:
#   exp_v14_scorecard_<stamp>.csv        (accuracy metrics)
#   exp_v14_double_count_<stamp>.csv     (per-channel attribution comparison)
#
# REQUIRES kernel state from steps/10_exp_fit_split.py.
# Run:   .venv/bin/python scripts/run_local.py 10 11   (or 11 alone right after 10)
# Colab: colab exec -s <session> -f steps/11_exp_scorecard.py --timeout 7200
# =============================================================================
import datetime
import os

import numpy as np
import pandas as pd

_missing = [n for n in ('mmm_total', 'mmm_instore', 'mmm_digital', 'df_bq', 'times',
                        'holdout_mask', 'exp_meta', 'media_channels', 'media_spend_cols')
            if n not in globals()]
if _missing:
    raise RuntimeError(f"Missing kernel globals: {_missing}. Run steps/10_exp_fit_split.py first "
                       f"(state dies with the process locally - chain '10 11' in one invocation).")

import arviz as az
from meridian.analysis import analyzer as analyzer_module

_stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
MODELS = [('total', mmm_total), ('instore', mmm_instore), ('digital', mmm_digital)]

# --- 3) convergence ----------------------------------------------------------
print("=== Convergence (max r_hat over roi_m/beta_m/ec_m; gate: < 1.05) ===")
max_rhat = {}
for name, m in MODELS:
    summ = az.summary(m.inference_data, var_names=['roi_m', 'beta_m', 'ec_m'])
    max_rhat[name] = float(summ['r_hat'].max())
    flag = "OK" if max_rhat[name] < 1.05 else "FAIL - do not trust this model's numbers"
    print(f"  {name:8s} max r_hat = {max_rhat[name]:.3f}  [{flag}]")

# --- actuals on the model's weekly grid --------------------------------------
_act = df_bq.groupby('time')[['Conversions_Revenue', 'Conversions_Revenue_InStore',
                              'Conversions_Revenue_Digital']].sum().reindex(times)
actual = {
    'total':   _act['Conversions_Revenue'].to_numpy(dtype=float),
    'instore': _act['Conversions_Revenue_InStore'].to_numpy(dtype=float),
    'digital': _act['Conversions_Revenue_Digital'].to_numpy(dtype=float),
}

# --- weekly posterior-mean predictions --------------------------------------
def _weekly_pred(m):
    inc = analyzer_module.Analyzer(m).expected_outcome(
        use_posterior=True, aggregate_times=False).numpy()  # (chains, draws, n_times)
    return inc.mean(axis=(0, 1))

pred = {name: _weekly_pred(m) for name, m in MODELS}
pred['split_sum'] = pred['instore'] + pred['digital']


def _metrics(y, yhat, mask):
    y, yhat = y[mask], yhat[mask]
    sse = float(np.sum((y - yhat) ** 2))
    sst = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else np.nan
    abs_err = np.abs(y - yhat)
    with np.errstate(divide='ignore', invalid='ignore'):
        mape = float(np.nanmean(np.where(y != 0, abs_err / np.abs(y), np.nan)))
    wmape = float(np.sum(abs_err) / np.sum(np.abs(y))) if np.sum(np.abs(y)) > 0 else np.nan
    return r2, mape, wmape


train_mask = ~holdout_mask
rows = []
for label, target, p in [
    ('BASELINE total model -> actual total',        'total',   pred['total']),
    ('SPLIT  instore+digital -> actual total',      'total',   pred['split_sum']),
    ('  (diag) instore model -> actual instore',    'instore', pred['instore']),
    ('  (diag) digital model -> actual digital',    'digital', pred['digital']),
]:
    for window, mask in [('train', train_mask), ('HOLDOUT', holdout_mask)]:
        r2, mape, wmape = _metrics(actual[target], p, mask)
        rows.append({'comparison': label, 'window': window,
                     'r_squared': r2, 'mape': mape, 'wmape': wmape})
score = pd.DataFrame(rows)

pd.set_option('display.float_format', lambda v: f'{v:,.4f}')
print("\n=== 1) Accuracy (holdout is the only window that matters) ===")
print(score.to_string(index=False))

# --- 2) double-counting check ------------------------------------------------
print("\n=== 2) Double-counting check (full-window incremental revenue per channel) ===")
def _channel_inc(m):
    inc = analyzer_module.Analyzer(m).incremental_outcome(
        include_non_paid_channels=False).numpy()  # (chains, draws, n_paid)
    return inc.mean(axis=(0, 1))

inc_t = _channel_inc(mmm_total)
inc_s = _channel_inc(mmm_instore)
inc_d = _channel_inc(mmm_digital)

spend = df_bq[media_spend_cols].sum().to_numpy(dtype=float)
dc = pd.DataFrame({
    'channel': media_channels,
    'spend': spend,
    'inc_rev_baseline': inc_t,
    'inc_rev_split_sum': inc_s + inc_d,
    'inc_rev_instore': inc_s,
    'inc_rev_digital': inc_d,
})
dc['ratio_split_vs_baseline'] = dc['inc_rev_split_sum'] / dc['inc_rev_baseline']
dc['roas_baseline'] = dc['inc_rev_baseline'] / dc['spend']
dc['roas_split']    = dc['inc_rev_split_sum'] / dc['spend']
dc['flag'] = np.where((dc['ratio_split_vs_baseline'] > 1.25) | (dc['ratio_split_vs_baseline'] < 0.8),
                      'CHECK', '')
pd.set_option('display.float_format', lambda v: f'{v:,.2f}')
print(dc.to_string(index=False))
_tot_ratio = dc['inc_rev_split_sum'].sum() / dc['inc_rev_baseline'].sum()
print(f"\nAll-channel incremental: split/baseline = {_tot_ratio:.2f} "
      f"({'inflated - double-counting likely' if _tot_ratio > 1.25 else 'within reason' if _tot_ratio > 0.8 else 'deflated - check'})")

# --- verdict -----------------------------------------------------------------
print("\n=== VERDICT ===")
_h = score[score['window'] == 'HOLDOUT']
_r2_base  = float(_h[_h['comparison'].str.startswith('BASELINE')]['r_squared'].iloc[0])
_r2_split = float(_h[_h['comparison'].str.startswith('SPLIT')]['r_squared'].iloc[0])
print(f"Holdout R^2 on actual total revenue: baseline {_r2_base:.4f} vs split {_r2_split:.4f} "
      f"-> {'SPLIT WINS' if _r2_split > _r2_base else 'BASELINE WINS'} on accuracy")
_conv_ok = all(v < 1.05 for v in max_rhat.values())
_dc_ok = bool(0.8 <= _tot_ratio <= 1.25)
print(f"Convergence gate: {'pass' if _conv_ok else 'FAIL'} | Double-count gate: "
      f"{'pass' if _dc_ok else 'FAIL'}")
print("Promote the split only if it wins holdout AND passes both gates. "
      "Log the outcome in docs/SESSION_LOG.md either way.")

# --- exports -----------------------------------------------------------------
for df_out, name in [(score, 'scorecard'), (dc, 'double_count')]:
    df_out = df_out.copy()
    df_out['exported_at'] = _stamp
    for k, v in exp_meta.items():
        df_out[k] = v
    path = os.path.join(out_dir, f"exp_v14_{name}_{_stamp}.csv")
    df_out.to_csv(path, index=False)
    print(f"Saved: {path}")
