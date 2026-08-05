# @title Step 03 - Spend-aligned ROAS by quarter + non-media driver attribution
# =============================================================================
# MIGRATION NOTE: this is cell 2 of MMMv13_2.ipynb, unchanged except for this
# header, an upfront kernel-state check, and ONE documentation/config repair:
# the notebook's comment + non_media_agg named Celebs as a non-media treatment,
# but the model's non_media_cols are actually [Vault_Drops, Email_sends,
# Redemptions_Other, StoreCount] (Celebs is a CONTROL - see step 01). The dead
# 'Celebs' agg entry is now 'Redemptions_Other': 'sum' - numerically identical
# to before (Redemptions_Other already fell back to 'sum'), the config just
# tells the truth now. Outputs: printed pivot tables (streamed to your
# terminal) + a timestamped CSV in the Drive folder.
#
# REQUIRES kernel state from step 01 (mmm, df_bq, media_channels,
# media_impression_cols, media_spend_cols, non_media_cols, out_dir).
# Run via:  colab exec -s <session> -f steps/03_roas_quarterly.py --timeout 7200
# =============================================================================
# ---------------------------------------------------------------------------
# WHY THIS EXISTS
# Default ROAS divides revenue *realized* in period P by spend in period P. Because media has adstock/lag
# (max_lag=12 weeks here), revenue from Q1 spend lands across Q1/Q2/Q3, making realized-period ROAS "wonky".
#
# This cell attributes every incremental-revenue dollar back to the QUARTER WHOSE MEDIA CAUSED IT. For each
# quarter Q it turns ON only the media that ran in Q (Meridian `media_selected_times`) and sums the FULL
# downstream incremental revenue across ALL later weeks (lagged tail pulled back). It also reports the old
# realized-period ROAS side-by-side so you can see the distortion the pull-back removes.
#
# ALSO IN THIS VERSION: per-quarter incremental revenue attributed to non-media TREATMENTS (Vault_Drops,
# Email_sends, Redemptions_Other, StoreCount) alongside their input values. Non-media treatments enter the
# model linearly with no adstock, so realized = aligned (no lag to pull back).
#
# NOT INCLUDED: model CONTROLS (Hurricanes, Category_Interest, LightningSales,
# Redemptions_Birthday_Signup, Celebs). Meridian's
# analyzer doesn't decompose them through incremental_outcome - they're absorbed into the model fit but
# aren't separately attributable here. (Possible future extension: manually compute gamma_c * X_c per
# quarter from the posterior.)
#
# CAVEAT - end of window: media in the final max_lag (12) weeks has part of its revenue tail beyond the
# data, which Meridian truncates. Quarters flagged tail_truncated=True understate true spend-aligned ROAS
# (revenue tail clipped). Earliest weeks are fine for the aligned view. Non-media has no tail issue.
# ---------------------------------------------------------------------------
import datetime
import inspect
import numpy as np
import pandas as pd
from meridian.analysis import analyzer as analyzer_module

_missing = [n for n in ('mmm', 'df_bq', 'media_channels', 'media_impression_cols',
                        'media_spend_cols', 'non_media_cols') if n not in globals()]
if _missing:
    raise RuntimeError(
        f"Missing kernel globals: {_missing}. Run steps/01_fit_model.py first "
        f"(or steps/load_model.py to restore a saved fit)."
    )

WITH_CI   = True     # add 90% posterior credible interval on the aligned ROAS / non-media inc-rev
WRITE_CSV = True

# Aggregation per non-media treatment for the per-quarter input value. Events/sends use sum; state-like
# vars (StoreCount) use mean. Falls back to 'sum' for any variable added without an explicit choice.
non_media_agg = {
    'Vault_Drops':       'sum',
    'Email_sends':       'sum',
    'Redemptions_Other': 'sum',
    'StoreCount':        'mean',
}

analyzer = analyzer_module.Analyzer(mmm)

# safety: confirm this Meridian build supports media-execution windowing
if 'media_selected_times' not in inspect.signature(analyzer.incremental_outcome).parameters:
    raise RuntimeError(
        "This Meridian build's incremental_outcome lacks 'media_selected_times'; "
        "upgrade google-meridian to use the pulled-back ROAS method."
    )

# --- canonical weekly grid the model actually uses --------------------------
times    = pd.to_datetime(np.asarray(mmm.input_data.time.values))
q_period = pd.PeriodIndex(times, freq='Q')
quarters = sorted(q_period.unique())

# paid-media channel order (returned by incremental_outcome with include_non_paid=False)
try:
    paid_channels = list(mmm.input_data.get_all_paid_channels())
except Exception:
    paid_channels = list(media_channels)

# non-media treatments. Pulls from globals (non_media_cols from the spec cell); falls back to
# Meridian's input_data accessor if not in globals.
try:
    nm_treatments = list(non_media_cols)
except NameError:
    nm_treatments = list(getattr(mmm.input_data, 'non_media_treatments', []) or [])

n_paid = len(paid_channels)
n_nm   = len(nm_treatments)

# --- spend & impressions per channel per quarter (summed over geos) ----------
spend_map = dict(zip(media_channels, media_spend_cols))
impr_map  = dict(zip(media_channels, media_impression_cols))

_agg_cols = media_spend_cols + media_impression_cols
g = df_bq[['time'] + _agg_cols].copy()
g['time'] = pd.to_datetime(g['time'])
g['q']    = pd.PeriodIndex(g['time'], freq='Q')
gq = g.groupby('q')[_agg_cols].sum()

# --- non-media input values per quarter (per-variable aggregation) ----------
if nm_treatments:
    nm_df = df_bq[['time'] + nm_treatments].copy()
    nm_df['time'] = pd.to_datetime(nm_df['time'])
    nm_df['q']    = pd.PeriodIndex(nm_df['time'], freq='Q')
    nm_by_q = pd.DataFrame(index=sorted(nm_df['q'].unique()))
    for var in nm_treatments:
        nm_by_q[var] = nm_df.groupby('q')[var].agg(non_media_agg.get(var, 'sum'))
else:
    nm_by_q = pd.DataFrame()

# --- end-of-window truncation flag ------------------------------------------
max_lag = int(getattr(mmm.model_spec, 'max_lag', 0) or 0)
last_complete_week = times.max() - pd.Timedelta(weeks=max_lag)

rows = []
_layout_warned = False  # one-shot warning if non-paid channel layout looks off

for q in quarters:
    wk_mask   = (q_period == q)
    qweeks    = times[wk_mask]
    qlabel    = str(q)
    in_gq     = q in gq.index
    truncated = bool(qweeks.max() > last_complete_week) if max_lag else False

    # 1) SPEND-ALIGNED ("pulled back") for PAID media: only media that ran in q is ON; sum the
    #    full incremental revenue it drives across ALL weeks (lag tail included).
    inc_aligned = analyzer.incremental_outcome(
        media_selected_times=wk_mask.tolist(),
        selected_times=None,
        aggregate_geos=True,
        aggregate_times=True,
        include_non_paid_channels=False,
    ).numpy()  # (chains, draws, n_paid)

    # 2) REALIZED in q for paid + non-media in ONE call (sliced). Paid slice is the "wonky" view;
    #    non-media slice is the only view of non-media (linear, no adstock so realized = aligned).
    #    Meridian convention is paid first then non-paid; sanity-checked on first quarter below.
    inc_realized_all = analyzer.incremental_outcome(
        media_selected_times=None,
        selected_times=wk_mask.tolist(),
        aggregate_geos=True,
        aggregate_times=True,
        include_non_paid_channels=True,
    ).numpy()  # expected shape: (chains, draws, n_paid + n_nm)

    if not _layout_warned:
        _expected, _actual = n_paid + n_nm, inc_realized_all.shape[-1]
        if _actual != _expected:
            print(f"WARNING: analyzer returned {_actual} channels with non_paid=True; expected paid + "
                  f"non-media = {_expected}. Non-media attribution may be misaligned if your model has "
                  f"organic media/RF channels between the paid and non-media slices.")
        _layout_warned = True

    inc_realized = inc_realized_all[:, :, :n_paid]
    inc_nonmedia = inc_realized_all[:, :, n_paid:n_paid + n_nm] if n_nm > 0 else None

    aligned_mean  = inc_aligned.mean(axis=(0, 1))
    realized_mean = inc_realized.mean(axis=(0, 1))
    nm_mean       = inc_nonmedia.mean(axis=(0, 1)) if inc_nonmedia is not None else None
    if WITH_CI:
        aligned_lo = np.percentile(inc_aligned,  5, axis=(0, 1))
        aligned_hi = np.percentile(inc_aligned, 95, axis=(0, 1))
        nm_lo      = np.percentile(inc_nonmedia,  5, axis=(0, 1)) if inc_nonmedia is not None else None
        nm_hi      = np.percentile(inc_nonmedia, 95, axis=(0, 1)) if inc_nonmedia is not None else None

    # PAID rows
    for j, ch in enumerate(paid_channels):
        s  = float(gq.loc[q, spend_map[ch]]) if (in_gq and ch in spend_map) else 0.0
        im = float(gq.loc[q, impr_map[ch]])  if (in_gq and ch in impr_map)  else 0.0
        rec = {
            'quarter'            : qlabel,
            'channel'            : ch,
            'type'               : 'paid',
            'spend'              : s,
            'impressions'        : im,
            'input_value'        : np.nan,
            'inc_rev_aligned'    : float(aligned_mean[j]),
            'roas_aligned'       : (aligned_mean[j] / s) if s > 0 else np.nan,
            'inc_rev_realized'   : float(realized_mean[j]),
            'roas_realized_wonky': (realized_mean[j] / s) if s > 0 else np.nan,
            'eff_per_input_unit' : np.nan,
            'tail_truncated'     : truncated,
        }
        if WITH_CI:
            rec['roas_aligned_lo'] = (aligned_lo[j] / s) if s > 0 else np.nan
            rec['roas_aligned_hi'] = (aligned_hi[j] / s) if s > 0 else np.nan
        rows.append(rec)

    # NON-MEDIA rows (one per treatment, only if analyzer returned non-paid)
    if nm_mean is not None:
        for k, treat in enumerate(nm_treatments):
            val = float(nm_by_q.loc[q, treat]) if (q in nm_by_q.index and treat in nm_by_q.columns) else 0.0
            inc = float(nm_mean[k])
            rec = {
                'quarter'            : qlabel,
                'channel'            : treat,
                'type'               : 'non_media',
                'spend'              : np.nan,
                'impressions'        : np.nan,
                'input_value'        : val,
                'inc_rev_aligned'    : np.nan,   # not applicable - no adstock on non-media
                'roas_aligned'       : np.nan,
                'inc_rev_realized'   : inc,
                'roas_realized_wonky': np.nan,
                'eff_per_input_unit' : (inc / val) if val != 0 else np.nan,
                'tail_truncated'     : False,    # non-media has no adstock tail
            }
            if WITH_CI:
                rec['roas_aligned_lo'] = np.nan
                rec['roas_aligned_hi'] = np.nan
                rec['inc_rev_lo']      = float(nm_lo[k])
                rec['inc_rev_hi']      = float(nm_hi[k])
            rows.append(rec)

roas_q = pd.DataFrame(rows)

# --- blended (all-paid-channel) ROAS per quarter -----------------------------
paid_mask = roas_q['type'] == 'paid'
blended = (roas_q[paid_mask].groupby('quarter')
                  .agg(spend=('spend', 'sum'),
                       impressions=('impressions', 'sum'),
                       inc_rev_aligned=('inc_rev_aligned', 'sum'),
                       inc_rev_realized=('inc_rev_realized', 'sum'),
                       tail_truncated=('tail_truncated', 'max'))
                  .reset_index())
blended['channel']             = 'ALL_PAID (blended)'
blended['type']                = 'paid_blend'
blended['roas_aligned']        = blended['inc_rev_aligned']  / blended['spend']
blended['roas_realized_wonky'] = blended['inc_rev_realized'] / blended['spend']
roas_q = pd.concat([roas_q, blended], ignore_index=True, sort=False)
roas_q = roas_q.sort_values(['quarter', 'type', 'channel']).reset_index(drop=True)

# --- stamp the export date/time onto the data AND the filename --------------
_exported_at = datetime.datetime.now()
roas_q['exported_at'] = _exported_at.strftime('%Y-%m-%d %H:%M:%S')

# wide pivots for quick eyeballing
pivot_aligned_paid = (roas_q[roas_q['type'] == 'paid']
                        .pivot(index='quarter', columns='channel', values='roas_aligned'))
pivot_nm_revenue   = (roas_q[roas_q['type'] == 'non_media']
                        .pivot(index='quarter', columns='channel', values='inc_rev_realized'))
pivot_nm_input     = (roas_q[roas_q['type'] == 'non_media']
                        .pivot(index='quarter', columns='channel', values='input_value'))

pd.set_option('display.float_format', lambda v: f'{v:,.2f}')
print("PAID media - spend-aligned ROAS by quarter (future incremental revenue pulled back to the spend that drove it):\n")
print(pivot_aligned_paid)
print("\nNON-MEDIA - incremental revenue attributed per quarter (linear effect, no adstock):\n")
print(pivot_nm_revenue)
print("\nNON-MEDIA - input values per quarter (sum or mean per variable, see non_media_agg):\n")
print(pivot_nm_input)
print(f"\nExport timestamp: {roas_q['exported_at'].iloc[0]}")

if WRITE_CSV:
    _dir = out_dir if 'out_dir' in globals() else '.'
    _stamp = _exported_at.strftime('%Y%m%d_%H%M%S')
    path = f"{_dir}/roas_by_quarter_spend_aligned_{_stamp}.csv"
    roas_q.to_csv(path, index=False)
    print(f"Saved: {path}")
