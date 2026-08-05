# @title Per-channel adstock decay profile (revenue by lag week)
# ---------------------------------------------------------------------------
# WHY THIS EXISTS
# Each channel has a different adstock spec (geometric for Search/Meta/PMAX/Amex,
# binomial for the Video group). This cell answers, per channel: of the
# incremental revenue a week's media eventually drives, what share lands in the
# week of impression (lag 0), the week after (lag +1), +2, ... up to max_lag.
#
# METHOD
# For each channel ch, pick a representative IMPULSE WEEK W_ch (the week ch's
# media activity peaked, restricted to >= max_lag weeks before the end of data
# so the full tail fits in-window). Then run ONE Meridian counterfactual with
# `media_selected_times` ON only at W_ch and OFF everywhere else and
# `aggregate_times=False`. The resulting incremental-outcome time series for ch
# is exactly  beta_ch * w_{ch,L} * Hill(activity_ch[W_ch])  at t = W_ch + L
# (because hill_before_adstock=True applies the saturation BEFORE the adstock
# convolution), so dividing by the sum recovers the adstock kernel directly.
# The shape is independent of spend level and of which W_ch we picked.
#
# NOTE on binomial adstock: the peak need not be at lag 0 - a "ramp" then decay
# is expected for video. half_life_wk and weeks_to_90pct handle this correctly
# because they're computed off the CUMULATIVE curve.
#
# Cost: n_channels (9) counterfactual sims. A few minutes on GPU.
# ---------------------------------------------------------------------------
import datetime
import numpy as np
import pandas as pd
from meridian.analysis import analyzer as analyzer_module

WITH_PLOT = True
WRITE_CSV = True

analyzer = analyzer_module.Analyzer(mmm)
max_lag  = int(getattr(mmm.model_spec, 'max_lag', 12) or 12)

# canonical weekly grid (the model's own time axis)
times   = pd.to_datetime(np.asarray(mmm.input_data.time.values))
n_times = len(times)

# paid channels - order matches incremental_outcome output channel dim
try:
    paid_channels = list(mmm.input_data.get_all_paid_channels())
except Exception:
    paid_channels = list(media_channels)

# channel -> media-activity column (Search = clicks, all others = impressions)
impr_map = dict(zip(media_channels, media_impression_cols))

# adstock spec per channel - for context in the printed table
try:
    adstock_spec = dict(mmm.model_spec.adstock_decay_spec or {})
except Exception:
    adstock_spec = {}

# weekly activity per channel, aligned to the model's time grid
act = df_bq[['time'] + media_impression_cols].copy()
act['time'] = pd.to_datetime(act['time'])
act = act.groupby('time')[media_impression_cols].sum().reindex(times)

# pick impulse week per channel: peak activity, restricted to leave the full
# max_lag tail inside the data window so the decay isn't truncated
safe_end = max(0, n_times - max_lag - 1)
impulse_idx, impulse_note = {}, {}
for ch in paid_channels:
    col = impr_map.get(ch)
    if col is None or col not in act.columns:
        impulse_idx[ch] = None
        impulse_note[ch] = 'no activity column mapped'
        continue
    series = act[col].fillna(0).to_numpy(dtype=float)
    safe_series = series.copy()
    if safe_end + 1 < n_times:
        safe_series[safe_end + 1:] = -1.0
    if safe_series.max() > 0:
        impulse_idx[ch]  = int(np.argmax(safe_series))
        impulse_note[ch] = 'peak activity in-window'
    elif series.max() > 0:
        impulse_idx[ch]  = int(np.argmax(series))
        impulse_note[ch] = 'peak falls in last max_lag wks - tail TRUNCATED'
    else:
        impulse_idx[ch]  = None
        impulse_note[ch] = 'no positive activity - cannot recover decay'

usable = [c for c in paid_channels if impulse_idx.get(c) is not None]
print(f"Computing per-channel decay - {len(usable)} channels x 1 counterfactual "
      f"sim each. A few minutes on GPU.")

# --- run one impulse counterfactual per channel ------------------------------
decay_rows = []
for ch in paid_channels:
    w_idx = impulse_idx.get(ch)
    if w_idx is None:
        continue
    mask = np.zeros(n_times, dtype=bool)
    mask[w_idx] = True

    inc = analyzer.incremental_outcome(
        media_selected_times=mask.tolist(),
        selected_times=None,
        aggregate_geos=True,
        aggregate_times=False,
        include_non_paid_channels=False,
    ).numpy()                                  # (chains, draws, n_times, n_channels)

    ch_idx   = paid_channels.index(ch)
    inc_mean = inc.mean(axis=(0, 1))[:, ch_idx]      # (n_times,) - this channel only
    end      = min(n_times, w_idx + max_lag + 1)
    tail     = inc_mean[w_idx:end]                   # values at lags 0..max_lag
    total    = float(tail.sum())
    if total <= 0:
        continue
    profile = tail / total
    cum     = np.cumsum(profile)
    for L, (frac, c) in enumerate(zip(profile, cum)):
        decay_rows.append({
            'channel'        : ch,
            'adstock'        : adstock_spec.get(ch, ''),
            'lag_weeks'      : L,
            'pct_of_revenue' : float(frac),
            'cumulative_pct' : float(c),
            'impulse_week'   : str(times[w_idx].date()),
            'impulse_note'   : impulse_note[ch],
        })

decay = pd.DataFrame(decay_rows)

# --- wide table: channels x lag ---------------------------------------------
wide = (decay.pivot(index='channel', columns='lag_weeks', values='pct_of_revenue')
             .reindex(paid_channels))
wide.columns = [f'wk+{L}' for L in wide.columns]

# --- per-channel summary: half-life, 90% lag, first-month concentration ------
def _lag_at_cum(g, thr):
    g = g.sort_values('lag_weeks')
    hit = g[g['cumulative_pct'] >= thr]
    return int(hit['lag_weeks'].iloc[0]) if len(hit) else np.nan

summary = []
for ch in paid_channels:
    g = decay[decay['channel'] == ch]
    if g.empty:
        summary.append({
            'channel': ch, 'adstock': adstock_spec.get(ch, ''),
            'pct_week_0': np.nan, 'pct_weeks_0_4': np.nan,
            'half_life_wk': np.nan, 'weeks_to_90pct': np.nan,
            'impulse_week': '', 'impulse_note': impulse_note.get(ch, ''),
        })
        continue
    s0  = g.loc[g['lag_weeks'] == 0, 'pct_of_revenue']
    s04 = g.loc[g['lag_weeks'] <= 4, 'pct_of_revenue'].sum()
    summary.append({
        'channel'        : ch,
        'adstock'        : adstock_spec.get(ch, ''),
        'pct_week_0'     : float(s0.iloc[0]) if len(s0) else np.nan,
        'pct_weeks_0_4'  : float(s04),
        'half_life_wk'   : _lag_at_cum(g, 0.50),
        'weeks_to_90pct' : _lag_at_cum(g, 0.90),
        'impulse_week'   : g['impulse_week'].iloc[0],
        'impulse_note'   : g['impulse_note'].iloc[0],
    })
summary_df = pd.DataFrame(summary).set_index('channel').reindex(paid_channels)

# --- stamp export date/time onto data + filenames ---------------------------
_exported_at = datetime.datetime.now()
decay['exported_at']      = _exported_at.strftime('%Y-%m-%d %H:%M:%S')
summary_df['exported_at'] = _exported_at.strftime('%Y-%m-%d %H:%M:%S')

pd.set_option('display.float_format', lambda v: f'{v:,.3f}')
print("\nShare of each channel's incremental revenue landing at lag L weeks:\n")
print(wide.fillna(0).to_string())
print("\nSummary - half-life, 90% lag, and concentration in first 5 weeks:\n")
print(summary_df[['adstock', 'pct_week_0', 'pct_weeks_0_4',
                  'half_life_wk', 'weeks_to_90pct', 'impulse_note']].to_string())

if WRITE_CSV:
    _dir   = out_dir if 'out_dir' in globals() else '.'
    _stamp = _exported_at.strftime('%Y%m%d_%H%M%S')
    p1 = f"{_dir}/decay_profile_by_channel_{_stamp}.csv"
    p2 = f"{_dir}/decay_summary_by_channel_{_stamp}.csv"
    decay.to_csv(p1, index=False)
    summary_df.to_csv(p2)
    print(f"\nSaved:\n  {p1}\n  {p2}")

if WITH_PLOT:
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharex=True)
    for ch in paid_channels:
        g = decay[decay['channel'] == ch].sort_values('lag_weeks')
        if g.empty:
            continue
        axes[0].plot(g['lag_weeks'], 100 * g['pct_of_revenue'], marker='o', label=ch)
        axes[1].plot(g['lag_weeks'], 100 * g['cumulative_pct'],  marker='o', label=ch)
    axes[0].set_title('% of channel revenue landing each lag week')
    axes[0].set_xlabel('Weeks since impression'); axes[0].set_ylabel('%')
    axes[1].set_title('Cumulative % of channel revenue by lag week')
    axes[1].set_xlabel('Weeks since impression'); axes[1].set_ylabel('%')
    axes[1].axhline(50, color='gray', linestyle=':',  linewidth=0.8)
    axes[1].axhline(90, color='gray', linestyle='--', linewidth=0.8)
    axes[1].legend(loc='lower right', fontsize=8)
    plt.tight_layout(); plt.show()
