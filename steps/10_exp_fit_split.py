# @title Step 10 - EXPERIMENT v14-revenue-split: fit 3 models with a holdout (baseline + InStore + Digital)
# =============================================================================
# THE EXPERIMENT (branch exp/v14-revenue-split)
# Hypothesis (Ken, 2026-08-05): splitting total revenue into channel-of-sale
# sub-models and summing their outputs may beat the single total-revenue model -
# different conversion paths (in-store vs digital) plausibly have different
# response dynamics that one aggregate model blurs.
#
# Design (2-way, NOT 4-way: InStore is ~95-98% of revenue and App/Vault have
# partial history - a per-stream model for those would be prior soup):
#   Model T ("baseline"): KPI = Conversions_Revenue          (v13 priors, unchanged)
#   Model S ("instore"):  KPI = Conversions_Revenue_InStore  (share-scaled priors)
#   Model D ("digital"):  KPI = Ecom + App + Vault           (share-scaled priors)
# All three are fit with the SAME holdout: the last HOLDOUT_WEEKS in-model weeks
# are excluded from the KPI likelihood (media still feeds adstock - Meridian
# ModelSpec.holdout_id semantics), so steps/11 can score honest out-of-sample
# accuracy: does pred(S) + pred(D) track actual total revenue better than
# pred(T) on weeks NONE of the models saw?
#
# The baseline is REFIT here (rather than reusing the production v13 fit)
# because a fair comparison needs all three models blind to the same weeks.
#
# HARD GATES before any sampling:
#   1. Split columns present in abc.mmm (else: apply sql/abc_mmm_view.sql).
#   2. Weekly reconciliation: InStore+Ecom+App+Vault == Conversions_Revenue
#      within $1 - if the splits don't sum to total, the experiment is invalid.
#
# PRIOR SCALING for sub-models: if a channel's incremental revenue split
# proportionally to revenue share, sub-model prior median ROAS = total median x
# share  =>  loc_sub = loc_v13 + ln(share). That allocation is a neutral first
# pass, so sigmas are WIDENED by SIGMA_WIDEN to admit it's a guess (e.g. Search
# is plausibly digital-heavier than revenue share suggests). Ken can override
# per-channel later; log any override in docs/SESSION_LOG.md.
#
# CONFIG SYNC: channel lists and v13 prior tensors are copied from
# steps/01_fit_model.py and MUST stay in sync with it.
#
# KERNEL STATE OUT: mmm_total, mmm_instore, mmm_digital, df_bq, times,
# holdout_mask, exp_meta, plus the usual channel lists / credentials / out_dir.
# Run:  .venv/bin/python scripts/run_local.py 00 10 11        (~15 min local)
# Colab: colab exec -s <session> -f steps/10_exp_fit_split.py --timeout 21600
# =============================================================================

HOLDOUT_WEEKS = 26     # last N in-model weeks scored out-of-sample
SIGMA_WIDEN   = 0.15   # added to v13 roi_sigma for sub-models (allocation uncertainty)
RECON_TOL_USD = 1.0    # max tolerated |total - sum(splits)| per week (rounding = pennies)

import datetime
import os

import numpy as np
import pandas as pd

IS_COLAB = os.path.isdir('/content')
ALLOW_CPU = os.environ.get('MMM_ALLOW_CPU', '0') == '1'

# --- credentials + out_dir (same pattern as step 01) -------------------------
try:
    import google.auth
    credentials, _adc_project = google.auth.default(scopes=[
        'https://www.googleapis.com/auth/bigquery',
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets',
    ])
except Exception as _e:
    _fix = ("From your LOCAL terminal run `colab auth -s <session>` (interactive - human required)"
            if IS_COLAB else
            "Run the `gcloud auth application-default login --scopes=...` command from docs/SETUP.md")
    raise RuntimeError(f"No Google credentials available. {_fix}. Underlying error: {_e}")

_LOCAL_DRIVE_DIR = os.path.expanduser(
    '~/Library/CloudStorage/GoogleDrive-ken@donutanalytics.com/My Drive/ABC/MMM')
out_dir = os.environ.get('MMM_OUT_DIR') or (
    '/content/drive/MyDrive/ABC/MMM' if IS_COLAB else _LOCAL_DRIVE_DIR)

import pandas_gbq
import tensorflow as tf
import tensorflow_probability as tfp
from meridian.data import data_frame_input_data_builder as builder_module
from meridian.model import model as mmm_module
from meridian.model import prior_distribution
from meridian.model import spec

_gpu_available = len(tf.config.list_physical_devices('GPU')) > 0
print("GPU Available:", _gpu_available, "| TF", tf.__version__)
if not _gpu_available and not ALLOW_CPU:
    raise RuntimeError("No GPU and MMM_ALLOW_CPU unset - see steps/01 for context.")

# --- data pull ---------------------------------------------------------------
project_id = 'donut-426'
view_sql = """SELECT * FROM abc.mmm WHERE Model_Dates = 'In Model'"""
df_bq = pandas_gbq.read_gbq(view_sql, project_id=project_id)
df_bq['time'] = pd.to_datetime(df_bq['time'])
df_bq = df_bq.sort_values('time').reset_index(drop=True)
print("Data pulled. Shape:", df_bq.shape)

# --- GATE 1: split columns present -------------------------------------------
SPLIT_COLS = ['Conversions_Revenue_InStore', 'Conversions_Revenue_Ecom',
              'Conversions_Revenue_App', 'Conversions_Revenue_Vault']
_missing_cols = [c for c in SPLIT_COLS if c not in df_bq.columns]
if _missing_cols:
    raise RuntimeError(
        f"Revenue split columns missing from abc.mmm: {_missing_cols}. "
        f"Apply sql/abc_mmm_view.sql to BigQuery first (see file header for how)."
    )

# --- GATE 2: weekly reconciliation ------------------------------------------
_split_sum = df_bq[SPLIT_COLS].fillna(0).sum(axis=1)
_recon_err = (df_bq['Conversions_Revenue'] - _split_sum).abs()
_worst = _recon_err.max()
print(f"Reconciliation: worst weekly |total - sum(splits)| = ${_worst:,.2f}")
if _worst > RECON_TOL_USD:
    _bad = df_bq.loc[_recon_err > RECON_TOL_USD, ['time', 'Conversions_Revenue'] + SPLIT_COLS]
    print(_bad.head(10).to_string())
    raise RuntimeError(
        f"Splits do NOT reconcile to total revenue (worst ${_worst:,.2f} > ${RECON_TOL_USD}). "
        f"Fix the data before trusting any split-model result."
    )
print("Reconciliation PASSED - splits sum to total within tolerance.")

# --- KPIs --------------------------------------------------------------------
df_bq['Conversions_Revenue_Digital'] = (
    df_bq['Conversions_Revenue_Ecom'].fillna(0)
    + df_bq['Conversions_Revenue_App'].fillna(0)
    + df_bq['Conversions_Revenue_Vault'].fillna(0)
)

_total_rev   = float(df_bq['Conversions_Revenue'].sum())
share_instore = float(df_bq['Conversions_Revenue_InStore'].sum()) / _total_rev
share_digital = float(df_bq['Conversions_Revenue_Digital'].sum()) / _total_rev
_last52 = df_bq.tail(52)
_share_digital_52 = float(_last52['Conversions_Revenue_Digital'].sum()) / float(_last52['Conversions_Revenue'].sum())
print(f"Revenue shares (full in-model window): InStore {share_instore:.1%}, Digital {share_digital:.1%}")
print(f"  (Digital share last 52 wks: {_share_digital_52:.1%} - growing stream; share-scaled "
      f"priors use the full-window share, sigmas widened by {SIGMA_WIDEN} to compensate)")

# --- channel / variable definitions (SYNC WITH steps/01_fit_model.py) --------
media_channels = ['Meta', 'Search', 'PMAX', 'Amex',
                  'Video_Epsilon', 'Video_Google', 'Video_Hulu',
                  'Video_MNTN', 'Video_Paramount']
media_impression_cols = ['Meta_impression', 'Search_click', 'PMAX_impression', 'Amex_impression',
                         'Video_Epsilon_impression', 'Video_Google_impression', 'Video_Hulu_impression',
                         'Video_MNTN_impression', 'Video_Paramount_impression']
media_spend_cols = [f"{ch}_spend" for ch in media_channels]
non_media_cols = ['Vault_Drops','Email_sends','Redemptions_Other','StoreCount']
control_cols = ['Category_Interest', 'Hurricanes', 'LightningSales', 'Redemptions_Birthday_Signup','Celebs']

# --- v13 priors (SYNC WITH steps/01_fit_model.py) ----------------------------
roi_mu_v13 = np.array([1.40, 1.35, 1.15, 1.15, 1.60, 1.65, 1.20, 1.60, 1.40], dtype=np.float32)
roi_sigma_v13 = np.array([0.40, 0.28, 0.45, 0.45, 0.50, 0.50, 0.50, 0.50, 0.50], dtype=np.float32)
alpha_conc1 = tf.constant([2.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0], dtype=tf.float32)
alpha_conc0 = tf.constant([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0], dtype=tf.float32)
ec_mu = tf.constant([1.0] * 9, dtype=tf.float32)
ec_sigma = tf.constant([0.5] * 9, dtype=tf.float32)
adstock_map = {
    "Search": "geometric", "Meta": "geometric", "PMAX": "geometric", "Amex": "geometric",
    "Video_Epsilon": "binomial", "Video_Google": "binomial", "Video_Hulu": "binomial",
    "Video_MNTN": "binomial", "Video_Paramount": "binomial",
}


def _build_input(kpi_col):
    b = builder_module.DataFrameInputDataBuilder(kpi_type='revenue', default_kpi_column=kpi_col)
    b = b.with_kpi(df_bq)
    b = b.with_media(df_bq, media_cols=media_impression_cols,
                     media_spend_cols=media_spend_cols, media_channels=media_channels)
    if 'population' in df_bq.columns:
        b = b.with_population(df_bq, population_col='population')
    b = b.with_non_media_treatments(df_bq, non_media_treatment_cols=non_media_cols)
    b = b.with_controls(df_bq, control_cols=control_cols)
    return b.build()


# holdout mask on the model's own time grid (last HOLDOUT_WEEKS in-model weeks)
_input_total = _build_input('Conversions_Revenue')
times = pd.to_datetime(np.asarray(_input_total.time.values))
n_times = len(times)
holdout_mask = np.zeros(n_times, dtype=bool)
holdout_mask[-HOLDOUT_WEEKS:] = True
print(f"Holdout: last {HOLDOUT_WEEKS} of {n_times} weeks "
      f"({times[holdout_mask].min().date()} -> {times[holdout_mask].max().date()})")


def _fit(input_data, roi_loc, roi_scale, label):
    prior = prior_distribution.PriorDistribution(
        roi_m=tfp.distributions.LogNormal(loc=tf.constant(roi_loc), scale=tf.constant(roi_scale)),
        alpha_m=tfp.distributions.Beta(concentration1=alpha_conc1, concentration0=alpha_conc0),
        ec_m=tfp.distributions.TruncatedNormal(loc=ec_mu, scale=ec_sigma, low=0.1, high=10.0),
    )
    model_spec = spec.ModelSpec(
        prior=prior,
        media_effects_dist='log_normal',   # inert nationally (reset to 'normal') - kept for parity
        adstock_decay_spec=adstock_map,
        max_lag=12,
        hill_before_adstock=True,
        holdout_id=holdout_mask,
    )
    m = mmm_module.Meridian(input_data=input_data, model_spec=model_spec)
    print(f"[{label}] sampling (v13 params: 20 chains x 3000 keep)...")
    _t0 = datetime.datetime.now()
    m.sample_prior(500)
    m.sample_posterior(n_chains=20, n_adapt=3000, n_burnin=1000, n_keep=3000, seed=0,
                       dual_averaging_kwargs={'target_accept_prob': 0.85})
    print(f"[{label}] done in {(datetime.datetime.now() - _t0).total_seconds():,.0f}s")
    return m


# sub-model priors: proportional-share medians, widened sigmas
_loc_instore = (roi_mu_v13 + np.log(share_instore)).astype(np.float32)
_loc_digital = (roi_mu_v13 + np.log(share_digital)).astype(np.float32)
_sigma_sub   = (roi_sigma_v13 + SIGMA_WIDEN).astype(np.float32)
print("Sub-model prior median ROAS (InStore):",
      np.round(np.exp(_loc_instore), 2).tolist())
print("Sub-model prior median ROAS (Digital):",
      np.round(np.exp(_loc_digital), 2).tolist())

mmm_total   = _fit(_input_total, roi_mu_v13, roi_sigma_v13, 'T total-baseline')
mmm_instore = _fit(_build_input('Conversions_Revenue_InStore'), _loc_instore, _sigma_sub, 'S instore')
mmm_digital = _fit(_build_input('Conversions_Revenue_Digital'), _loc_digital, _sigma_sub, 'D digital')

exp_meta = {
    'experiment': 'v14-revenue-split',
    'holdout_weeks': HOLDOUT_WEEKS,
    'sigma_widen': SIGMA_WIDEN,
    'share_instore': share_instore,
    'share_digital': share_digital,
    'fit_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
}
print("\nAll 3 models fit. Kernel globals: mmm_total, mmm_instore, mmm_digital, df_bq, times, "
      "holdout_mask, exp_meta, channel lists.")
print("NEXT: steps/11_exp_scorecard.py")
