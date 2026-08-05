# @title Step 12 - EXPERIMENT v15-channel-consolidation: 9 channels -> 3 (Search+PMAX, Social, Video), Amex dropped
# =============================================================================
# THE EXPERIMENT (branch exp/v15-channel-consolidation)
# Hypothesis (Ken, 2026-08-05): v13's per-partner video posteriors are mostly
# prior-driven (v12's uniform priors collapsed all five to ~5.5x; v13 got
# differentiation by construction; the five decay profiles are near-identical).
# Consolidating channels should give fewer, better-identified response curves
# whose ROAS is driven by DATA rather than priors.
#
# Ken's chosen grouping (2026-08-05):
#   Search_PMAX : Search + PMAX combined
#   Social      : Meta (renamed)
#   Video_All   : the 5 video partners combined (Epsilon, Google, Hulu, MNTN,
#                 Paramount - summed from partner columns, NOT the view's
#                 Video_* aggregate, which includes Peacock that v13 excludes)
#   Amex        : DROPPED from the model entirely. Its ~$2.1M baseline-model
#                 incremental has to re-home (baseline or other channels) -
#                 step 13 quantifies where it went.
#
# MEDIA METRIC NOTE: v13 uses CLICKS for Search but impressions for PMAX. A
# combined channel needs one unit, so Search_PMAX uses IMPRESSIONS for both -
# a deliberate deviation from v13's clicks choice, revisit if the combined
# Search response looks degraded.
#
# DESIGN: two models, same KPI (total revenue), same 26-week holdout
# (ModelSpec.holdout_id), fit back-to-back:
#   B = v13 baseline (9 channels, v13 priors) - refit so comparison is fair
#   C = consolidated (3 channels, spend-weighted blended priors)
# Single-model-vs-single-model: no double-counting risk this time. Step 13
# scores holdout accuracy, grouped attribution parity, and posterior width.
#
# PRIORS for consolidated channels: spend-weighted blends of the v13 medians
# (in ROAS space, then back to log-space loc). Sigmas: Search_PMAX 0.35 (both
# parts were tight-ish), Social 0.40 (= v13 Meta), Video_All 0.40 (tighter than
# the per-partner 0.50 - a combined channel has real signal to earn it).
#
# CONFIG SYNC: v13 lists/priors copied from steps/01_fit_model.py - keep in sync.
# KERNEL STATE OUT: mmm_baseline, mmm_consolidated, df_bq, times, holdout_mask,
# exp_meta, both channel-list sets, credentials, out_dir.
# Run:  caffeinate -i .venv/bin/python scripts/run_local.py 00 12 13   (~10 min)
# Colab: colab exec -s <session> -f steps/12_exp_fit_consolidated.py --timeout 21600
# =============================================================================

HOLDOUT_WEEKS = 26

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

# --- v13 config (SYNC WITH steps/01_fit_model.py) ----------------------------
media_channels_v13 = ['Meta', 'Search', 'PMAX', 'Amex',
                      'Video_Epsilon', 'Video_Google', 'Video_Hulu',
                      'Video_MNTN', 'Video_Paramount']
media_impression_cols_v13 = ['Meta_impression', 'Search_click', 'PMAX_impression', 'Amex_impression',
                             'Video_Epsilon_impression', 'Video_Google_impression', 'Video_Hulu_impression',
                             'Video_MNTN_impression', 'Video_Paramount_impression']
media_spend_cols_v13 = [f"{ch}_spend" for ch in media_channels_v13]
non_media_cols = ['Vault_Drops','Email_sends','Redemptions_Other','StoreCount']
control_cols = ['Category_Interest', 'Hurricanes', 'LightningSales', 'Redemptions_Birthday_Signup','Celebs']

roi_mu_v13 = np.array([1.40, 1.35, 1.15, 1.15, 1.60, 1.65, 1.20, 1.60, 1.40], dtype=np.float32)
roi_sigma_v13 = np.array([0.40, 0.28, 0.45, 0.45, 0.50, 0.50, 0.50, 0.50, 0.50], dtype=np.float32)
alpha_conc1_v13 = tf.constant([2.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0], dtype=tf.float32)
alpha_conc0_v13 = tf.constant([2.0] * 9, dtype=tf.float32)
adstock_map_v13 = {
    "Search": "geometric", "Meta": "geometric", "PMAX": "geometric", "Amex": "geometric",
    "Video_Epsilon": "binomial", "Video_Google": "binomial", "Video_Hulu": "binomial",
    "Video_MNTN": "binomial", "Video_Paramount": "binomial",
}

# --- consolidated channel construction ---------------------------------------
_VIDEO_PARTNERS = ['Video_Epsilon', 'Video_Google', 'Video_Hulu', 'Video_MNTN', 'Video_Paramount']
df_bq['SearchPMAX_impression'] = df_bq['Search_impression'] + df_bq['PMAX_impression']
df_bq['SearchPMAX_spend']      = df_bq['Search_spend'] + df_bq['PMAX_spend']
df_bq['Social_impression']     = df_bq['Meta_impression']
df_bq['Social_spend']          = df_bq['Meta_spend']
df_bq['VideoAll_impression']   = sum(df_bq[f'{p}_impression'] for p in _VIDEO_PARTNERS)
df_bq['VideoAll_spend']        = sum(df_bq[f'{p}_spend'] for p in _VIDEO_PARTNERS)

media_channels_cons = ['Search_PMAX', 'Social', 'Video_All']
media_impression_cols_cons = ['SearchPMAX_impression', 'Social_impression', 'VideoAll_impression']
media_spend_cols_cons = ['SearchPMAX_spend', 'Social_spend', 'VideoAll_spend']

_amex_spend = float(df_bq['Amex_spend'].sum())
print(f"Amex is DROPPED from the consolidated model (${_amex_spend:,.0f} spend, "
      f"~$2.1M incremental in v13) - step 13 reports where its revenue re-homes.")

# --- consolidated priors: spend-weighted blends of v13 medians ---------------
def _blend_loc(channels):
    idx = [media_channels_v13.index(c) for c in channels]
    w = np.array([df_bq[media_spend_cols_v13[i]].sum() for i in idx], dtype=float)
    w = w / w.sum()
    blended_median = float(np.sum(w * np.exp(roi_mu_v13[idx])))
    return np.float32(np.log(blended_median)), dict(zip(channels, np.round(w, 3)))

_loc_searchpmax, _w_sp = _blend_loc(['Search', 'PMAX'])
_loc_video, _w_v = _blend_loc(_VIDEO_PARTNERS)
roi_mu_cons = np.array([_loc_searchpmax, 1.40, _loc_video], dtype=np.float32)
roi_sigma_cons = np.array([0.35, 0.40, 0.40], dtype=np.float32)
print(f"Consolidated prior median ROAS: Search_PMAX {np.exp(_loc_searchpmax):.2f} "
      f"(spend weights {_w_sp}), Social {np.exp(1.40):.2f}, "
      f"Video_All {np.exp(_loc_video):.2f} (spend weights {_w_v})")

alpha_conc1_cons = tf.constant([2.0, 2.0, 3.0], dtype=tf.float32)  # video keeps slow-decay tilt
alpha_conc0_cons = tf.constant([2.0, 2.0, 2.0], dtype=tf.float32)
adstock_map_cons = {"Search_PMAX": "geometric", "Social": "geometric", "Video_All": "binomial"}


def _build_input(media_cols, spend_cols, channels):
    b = builder_module.DataFrameInputDataBuilder(kpi_type='revenue',
                                                 default_kpi_column='Conversions_Revenue')
    b = b.with_kpi(df_bq)
    b = b.with_media(df_bq, media_cols=media_cols, media_spend_cols=spend_cols,
                     media_channels=channels)
    if 'population' in df_bq.columns:
        b = b.with_population(df_bq, population_col='population')
    b = b.with_non_media_treatments(df_bq, non_media_treatment_cols=non_media_cols)
    b = b.with_controls(df_bq, control_cols=control_cols)
    return b.build()


_input_base = _build_input(media_impression_cols_v13, media_spend_cols_v13, media_channels_v13)
_input_cons = _build_input(media_impression_cols_cons, media_spend_cols_cons, media_channels_cons)

times = pd.to_datetime(np.asarray(_input_base.time.values))
n_times = len(times)
holdout_mask = np.zeros(n_times, dtype=bool)
holdout_mask[-HOLDOUT_WEEKS:] = True
print(f"Holdout: last {HOLDOUT_WEEKS} of {n_times} weeks "
      f"({times[holdout_mask].min().date()} -> {times[holdout_mask].max().date()})")


def _fit(input_data, roi_loc, roi_scale, a1, a0, ads_map, n_ch, label):
    prior = prior_distribution.PriorDistribution(
        roi_m=tfp.distributions.LogNormal(loc=tf.constant(roi_loc), scale=tf.constant(roi_scale)),
        alpha_m=tfp.distributions.Beta(concentration1=a1, concentration0=a0),
        ec_m=tfp.distributions.TruncatedNormal(
            loc=tf.constant([1.0] * n_ch, dtype=tf.float32),
            scale=tf.constant([0.5] * n_ch, dtype=tf.float32), low=0.1, high=10.0),
    )
    model_spec = spec.ModelSpec(
        prior=prior,
        media_effects_dist='log_normal',   # inert nationally - kept for parity
        adstock_decay_spec=ads_map,
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


mmm_baseline = _fit(_input_base, roi_mu_v13, roi_sigma_v13,
                    alpha_conc1_v13, alpha_conc0_v13, adstock_map_v13, 9, 'B v13-baseline')
mmm_consolidated = _fit(_input_cons, roi_mu_cons, roi_sigma_cons,
                        alpha_conc1_cons, alpha_conc0_cons, adstock_map_cons, 3, 'C consolidated')

exp_meta = {
    'experiment': 'v15-channel-consolidation',
    'grouping': 'Search_PMAX; Social(Meta); Video_All(5 partners); Amex dropped',
    'holdout_weeks': HOLDOUT_WEEKS,
    'fit_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
}
print("\nBoth models fit. Kernel globals: mmm_baseline, mmm_consolidated, df_bq, times, "
      "holdout_mask, exp_meta, channel lists (v13 + cons).")
print("NEXT: steps/13_exp_scorecard_consolidated.py")
