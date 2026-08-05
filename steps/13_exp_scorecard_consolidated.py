# @title Step 13 - EXPERIMENT v15-channel-consolidation: scorecard (holdout + attribution parity + posterior width)
# =============================================================================
# Scores the 3-channel consolidated model against the refit 9-channel baseline.
# Both are single models on the same KPI, so unlike v14 there is NO
# double-counting concern - the questions are:
#
# 1. HOLDOUT ACCURACY: does the 3-channel model predict the 26 unseen weeks at
#    least as well as the 9-channel model? (Fewer parameters CAN generalize
#    better; a tie is a win for the simpler model.)
#
# 2. ATTRIBUTION PARITY: grouped incremental revenue - baseline's Search+PMAX
#    vs consolidated Search_PMAX, Meta vs Social, 5-video-sum vs Video_All.
#    Also: where did Amex's ~$2.1M of baseline incremental go? (It was dropped
#    from the consolidated model; whatever the surviving channels + baseline
#    absorb shows up as group ratios != 1.)
#
# 3. POSTERIOR WIDTH (the interpretability headline): v13's per-partner video
#    ROAS intervals are wide AND prior-driven; the consolidated Video_All
#    should be tighter and data-driven. Reports ROI mean + 90% CI for every
#    channel in both models.
#
# Convergence gate as always: max r_hat < 1.05 per model.
#
# Outputs: printed verdict + stamped CSVs in <out_dir>:
#   exp_v15_scorecard_<stamp>.csv, exp_v15_attribution_<stamp>.csv,
#   exp_v15_roi_posteriors_<stamp>.csv
#
# REQUIRES kernel state from steps/12_exp_fit_consolidated.py.
# Run:   .venv/bin/python scripts/run_local.py 12 13   (chain in one invocation)
# Colab: colab exec -s <session> -f steps/13_exp_scorecard_consolidated.py --timeout 7200
# =============================================================================
import datetime
import os

import numpy as np
import pandas as pd

_missing = [n for n in ('mmm_baseline', 'mmm_consolidated', 'df_bq', 'times', 'holdout_mask',
                        'exp_meta', 'media_channels_v13', 'media_spend_cols_v13',
                        'media_channels_cons', 'media_spend_cols_cons')
            if n not in globals()]
if _missing:
    raise RuntimeError(f"Missing kernel globals: {_missing}. Run steps/12_exp_fit_consolidated.py "
                       f"first (chain '12 13' in one run_local invocation).")

import arviz as az
from meridian.analysis import analyzer as analyzer_module

_stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
MODELS = [('baseline_9ch', mmm_baseline), ('consolidated_3ch', mmm_consolidated)]

# --- convergence -------------------------------------------------------------
print("=== Convergence (max r_hat over roi_m/beta_m/ec_m; gate: < 1.05) ===")
max_rhat = {}
for name, m in MODELS:
    summ = az.summary(m.inference_data, var_names=['roi_m', 'beta_m', 'ec_m'])
    max_rhat[name] = float(summ['r_hat'].max())
    flag = "OK" if max_rhat[name] < 1.05 else "FAIL - numbers untrustworthy"
    print(f"  {name:18s} max r_hat = {max_rhat[name]:.3f}  [{flag}]")

# --- 1) holdout accuracy -----------------------------------------------------
actual_total = (df_bq.groupby('time')['Conversions_Revenue'].sum()
                .reindex(times).to_numpy(dtype=float))

def _weekly_pred(m):
    inc = analyzer_module.Analyzer(m).expected_outcome(
        use_posterior=True, aggregate_times=False).numpy()
    return inc.mean(axis=(0, 1))

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
for name, m in MODELS:
    p = _weekly_pred(m)
    for window, mask in [('train', train_mask), ('HOLDOUT', holdout_mask)]:
        r2, mape, wmape = _metrics(actual_total, p, mask)
        rows.append({'model': name, 'window': window, 'r_squared': r2, 'mape': mape, 'wmape': wmape})
score = pd.DataFrame(rows)
pd.set_option('display.float_format', lambda v: f'{v:,.4f}')
print("\n=== 1) Accuracy vs actual total revenue ===")
print(score.to_string(index=False))

# --- 2) attribution parity by group ------------------------------------------
GROUPS = {
    'Search_PMAX': ['Search', 'PMAX'],
    'Social':      ['Meta'],
    'Video_All':   ['Video_Epsilon', 'Video_Google', 'Video_Hulu', 'Video_MNTN', 'Video_Paramount'],
}

def _channel_inc(m):
    inc = analyzer_module.Analyzer(m).incremental_outcome(
        include_non_paid_channels=False).numpy()
    return inc.mean(axis=(0, 1))

inc_base = dict(zip(media_channels_v13, _channel_inc(mmm_baseline)))
inc_cons = dict(zip(media_channels_cons, _channel_inc(mmm_consolidated)))
spend_base = dict(zip(media_channels_v13,
                      df_bq[media_spend_cols_v13].sum().to_numpy(dtype=float)))
spend_cons = dict(zip(media_channels_cons,
                      df_bq[media_spend_cols_cons].sum().to_numpy(dtype=float)))

att_rows = []
for gname, members in GROUPS.items():
    b_inc = float(sum(inc_base[c] for c in members))
    c_inc = float(inc_cons[gname])
    s = float(spend_cons[gname])
    att_rows.append({'group': gname, 'spend': s,
                     'inc_rev_baseline_grouped': b_inc, 'inc_rev_consolidated': c_inc,
                     'ratio_cons_vs_base': c_inc / b_inc if b_inc else np.nan,
                     'roas_baseline': b_inc / s if s else np.nan,
                     'roas_consolidated': c_inc / s if s else np.nan})
att_rows.append({'group': 'Amex (DROPPED in consolidated)', 'spend': spend_base['Amex'],
                 'inc_rev_baseline_grouped': float(inc_base['Amex']),
                 'inc_rev_consolidated': 0.0, 'ratio_cons_vs_base': 0.0,
                 'roas_baseline': float(inc_base['Amex']) / spend_base['Amex'],
                 'roas_consolidated': np.nan})
att = pd.DataFrame(att_rows)
pd.set_option('display.float_format', lambda v: f'{v:,.2f}')
print("\n=== 2) Attribution parity (full-window incremental revenue, grouped) ===")
print(att.to_string(index=False))
_base_total = float(sum(inc_base.values()))
_cons_total = float(sum(inc_cons.values()))
print(f"\nTotal media incremental: baseline ${_base_total:,.0f} (incl Amex) vs "
      f"consolidated ${_cons_total:,.0f} | ratio excl-Amex "
      f"{_cons_total / (_base_total - inc_base['Amex']):.2f}")

# --- 3) ROI posterior width --------------------------------------------------
def _roi_table(m, channels, model_name):
    arr = m.inference_data.posterior['roi_m'].values  # (chains, draws, n_ch)
    flat = arr.reshape(-1, arr.shape[-1])
    out = []
    for j, ch in enumerate(channels):
        lo, mid, hi = np.percentile(flat[:, j], [5, 50, 95])
        out.append({'model': model_name, 'channel': ch, 'roi_p5': lo, 'roi_median': mid,
                    'roi_p95': hi, 'ci90_width': hi - lo, 'ci_ratio_hi_lo': hi / lo})
    return out

roi_tbl = pd.DataFrame(_roi_table(mmm_baseline, media_channels_v13, 'baseline_9ch')
                       + _roi_table(mmm_consolidated, media_channels_cons, 'consolidated_3ch'))
print("\n=== 3) ROI posteriors (median [p5, p95]; narrower CI = better identified) ===")
print(roi_tbl.to_string(index=False))

# --- verdict -----------------------------------------------------------------
print("\n=== VERDICT ===")
_h = score[score['window'] == 'HOLDOUT'].set_index('model')
_r2_b, _r2_c = float(_h.loc['baseline_9ch', 'r_squared']), float(_h.loc['consolidated_3ch', 'r_squared'])
_wmape_b, _wmape_c = float(_h.loc['baseline_9ch', 'wmape']), float(_h.loc['consolidated_3ch', 'wmape'])
print(f"Holdout: baseline R^2 {_r2_b:.4f} / wMAPE {_wmape_b:.4f}  vs  "
      f"consolidated R^2 {_r2_c:.4f} / wMAPE {_wmape_c:.4f}")
_conv_ok = all(v < 1.05 for v in max_rhat.values())
print(f"Convergence gate: {'pass' if _conv_ok else 'FAIL'}")
_vid_w_cons = float(roi_tbl[(roi_tbl['model'] == 'consolidated_3ch')
                            & (roi_tbl['channel'] == 'Video_All')]['ci_ratio_hi_lo'].iloc[0])
print(f"Video identification: consolidated Video_All CI ratio (p95/p5) = {_vid_w_cons:.2f} "
      f"(compare against the per-partner rows above - v13's are ~e^(2*1.645*0.5) ≈ 5x when prior-driven)")
print("Read: prefer the consolidated model if holdout is >= baseline AND the grouped "
      "attribution is sane AND Video_All's CI is meaningfully tighter than the partner CIs. "
      "Amex's re-homed revenue is the wildcard - check the parity table. "
      "Log the outcome in docs/SESSION_LOG.md either way.")

# --- exports -----------------------------------------------------------------
for df_out, name in [(score, 'scorecard'), (att, 'attribution'), (roi_tbl, 'roi_posteriors')]:
    df_out = df_out.copy()
    df_out['exported_at'] = _stamp
    for k, v in exp_meta.items():
        df_out[k] = v
    path = os.path.join(out_dir, f"exp_v15_{name}_{_stamp}.csv")
    df_out.to_csv(path, index=False)
    print(f"Saved: {path}")
