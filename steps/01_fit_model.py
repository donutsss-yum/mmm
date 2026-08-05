# @title Step 01 - MMMv13 model spec + fit - takes about 8 min on A100
# =============================================================================
# MIGRATION NOTE (Colab web UI -> Colab CLI, 2026-08):
# This is cell 0 of MMMv13_2.ipynb with three mechanical changes; the MODEL IS
# UNCHANGED (same data pull, channels, priors, spec, and sampling params):
#   1. `!pip install ...` removed - deps are installed once per session from the
#      local terminal: colab install -s <session> -r requirements-colab.txt
#   2. `google.colab.auth.authenticate_user(...)` + `drive.mount(...)` replaced
#      with Application Default Credentials. Auth/mount are done ONCE per
#      session from the local terminal (both interactive, human required):
#        colab auth -s <session>
#        colab drivemount -s <session>
#   3. `out_dir` (Drive output folder) is defined HERE so steps 03/04 work even
#      if step 02 is skipped. Cell 1 originally defined it.
#
# KERNEL STATE: this step leaves `mmm`, `df_bq`, `credentials`, the channel
# lists, and `out_dir` in the kernel's global scope. Later steps (02-05) depend
# on them. The Colab CLI reattaches to the SAME kernel on every `colab exec`,
# so state persists until `colab stop` / `colab restart-kernel` / VM death.
# After a fit, run steps/save_model.py so you can recover with
# steps/load_model.py instead of re-sampling.
# =============================================================================

# =============================================================================
# CHANGES FROM v12:
# - non_media_cols: removed Conversions_BasketSize and Conversions_Pricing (confounding the fit; capturing demand-side
#   variation media should explain).
# - roi_mu for video: was [1.65 x 5] (uniform prior). Now per-partner, tiered by Ken's outside view of inventory type:
#     * Performance / demand-gen tier (high prior ROAS):  Google, MNTN, Epsilon
#     * Branding / awareness tier      (mid prior ROAS):   Hulu, Paramount
#   Paramount later bumped from 1.20 -> 1.40 after realized history showed consistent 4.6-6.2x ROAS.
# - roi_sigma for video: 0.25 -> 0.50 so 156 weeks of national data can move the posteriors off the prior. The old
#   0.25 was so tight that v12 video posteriors all collapsed to ~5.3-5.7x (basically still on the prior).
# - ec_sigma for video: 0.30 -> 0.50 to try to identify per-partner Hill saturation points. Didn't pan out empirically
#   (all video ec_m posteriors stayed near prior mean of 1.0), but no harm leaving loose.
# =============================================================================

# =============================================================================
# KNOWN LIMITATION - Google low-spend ROAS extrapolation:
# At low Google spend (~$9k/quarter) the model produces implausible aligned ROAS (20-30x), while at high spend
# ($217k in 2025Q4) it produces a credible 2.3x. The high-spend point is trustworthy; the low-spend reading is
# the model's Hill curve passing through near-zero data, NOT a measurement.
#
# Why this happens: Hill with slope=1 has marginal response = 1/ec at x=0. To fit both the high-spend saturation
# and the low-spend revenue, the model picks low ec and high beta - which inflates the low-spend extrapolation.
# No prior tweak cleanly fixes this without distorting fit elsewhere; the issue is the functional form.
#
# How to interpret: trust Google's ROAS at spend levels NEAR what it actually ran (~$10k-$220k/qtr based on history).
# Don't trust extrapolations far below that range. The scenario planner will recommend cutting Google to ~$10k/qtr
# at 30x - do NOT take that recommendation at face value. The real fix is a YouTube holdout / incrementality test
# for prior calibration on roi_m[Video_Google].
# =============================================================================

ALLOW_CPU = False  # set True only if you knowingly want a (very slow) CPU fit

# 1) Credentials - Application Default Credentials, set up on the VM by `colab auth`.
#    The `credentials` global is consumed later by step 05 (gspread upload to the dashboard sheet).
import datetime

try:
    import google.auth
    credentials, _adc_project = google.auth.default(scopes=[
        'https://www.googleapis.com/auth/bigquery',
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets',
    ])
except Exception as _e:
    raise RuntimeError(
        "No Google credentials on the VM. From your LOCAL terminal run "
        "`colab auth -s <session>` (interactive - human required), then re-run this step. "
        f"Underlying error: {type(_e).__name__}: {_e}"
    )

# Drive must be mounted for outputs (steps 02-05 write to Drive). Warn here, hard-checked in step 00.
import os
if not os.path.isdir('/content/drive/MyDrive'):
    print("WARNING: Google Drive is NOT mounted. Steps 02-05 will fail to write outputs. "
          "From your LOCAL terminal run `colab drivemount -s <session>` (interactive).")

# Drive output folder for ALL pipeline exports (HTML summaries, CSVs, model saves, diagnostics).
out_dir = '/content/drive/MyDrive/ABC/MMM'

# 3) Imports
import arviz as az
import numpy as np
import pandas as pd
import pandas_gbq
from meridian import constants
from meridian.analysis import optimizer as budget_optimizer_module
from meridian.analysis import summarizer
from meridian.analysis import visualizer
from meridian.data import data_frame_input_data_builder as builder_module
from meridian.model import model as mmm_module
from meridian.model import prior_distribution
from meridian.model import spec
import tensorflow as tf
import tensorflow_probability as tfp

# 4) Runtime checks
_gpu_available = len(tf.config.list_physical_devices('GPU')) > 0
print("GPU Available:", _gpu_available)
print("TensorFlow version:", tf.__version__)
if not _gpu_available and not ALLOW_CPU:
    raise RuntimeError(
        "No GPU on this runtime and ALLOW_CPU is False. Fitting on CPU takes hours. "
        "Provision with: colab stop -s <session>; colab new -s <session> --gpu A100"
    )

# 5) Pull data from BigQuery. abc.mmm is the weekly blender view (media + promos + controls);
#    'In Model' filter excludes weeks we don't want to fit (burn-in, hold-outs).
project_id = 'donut-426'
view_sql = """SELECT * FROM abc.mmm WHERE Model_Dates = 'In Model'"""

df_bq = pandas_gbq.read_gbq(view_sql, project_id=project_id)
if 'time' not in df_bq.columns:
    raise ValueError("Expected a 'time' column in BigQuery data.")
df_bq['time'] = pd.to_datetime(df_bq['time'])

# 6) Channel / variable definitions. CRITICAL: media_channels order must match media_impression_cols and
#    media_spend_cols index-for-index, AND must match the vectorized priors below (roi_mu[i] applies to
#    media_channels[i]). Don't reorder these lists without also reordering the prior tensors.
media_channels = ['Meta', 'Search', 'PMAX', 'Amex',
                  'Video_Epsilon', 'Video_Google', 'Video_Hulu',
                  'Video_MNTN', 'Video_Paramount']

# Per-channel media-activity metric. Note Search uses CLICKS, everything else (including Amex) uses IMPRESSIONS.
# This list is parallel to media_channels.
media_impression_cols = ['Meta_impression', 'Search_click', 'PMAX_impression', 'Amex_impression',
                         'Video_Epsilon_impression', 'Video_Google_impression', 'Video_Hulu_impression',
                         'Video_MNTN_impression', 'Video_Paramount_impression']

media_spend_cols = [f"{ch}_spend" for ch in media_channels]

# Non-media treatments enter the model linearly (no Hill/adstock). v13: removed Conversions_BasketSize and
# Conversions_Pricing - they were confounding the fit (capturing demand-side variation media should explain).
non_media_cols = ['Vault_Drops','Email_sends','Redemptions_Other','StoreCount']

# Controls also enter linearly. Redemptions split into Birthday/Signup vs Other so the structurally-elevated
# Birthday signup baseline doesn't wash out general redemption signal.
control_cols = ['Category_Interest', 'Hurricanes', 'LightningSales', 'Redemptions_Birthday_Signup','Celebs']

population_col = 'population' if 'population' in df_bq.columns else None

required_cols = (['time', 'geo', 'Conversions_Revenue']
                 + media_impression_cols + media_spend_cols
                 + non_media_cols + control_cols)
missing = [c for c in required_cols if c not in df_bq.columns]
if missing:
    raise ValueError(f"Missing columns: {missing}. Verify your BigQuery schema.")
print("All key columns present. Shape:", df_bq.shape)

# 7) Build Meridian InputData. KPI is revenue (continuous, dollars). Builder needs a 'geo' column; for a national
#    model this has a single value ('national_geo') and Meridian warns later that aggregate_geos=True is enforced
#    - that's expected.
builder = builder_module.DataFrameInputDataBuilder(
    kpi_type='revenue',
    default_kpi_column='Conversions_Revenue'
)
builder = builder.with_kpi(df_bq)
builder = builder.with_media(
    df_bq,
    media_cols=media_impression_cols,
    media_spend_cols=media_spend_cols,
    media_channels=media_channels
)
if population_col:
    builder = builder.with_population(df_bq, population_col=population_col)
builder = builder.with_non_media_treatments(df_bq, non_media_treatment_cols=non_media_cols)
builder = builder.with_controls(df_bq, control_cols=control_cols)
input_data = builder.build()
print("Input Data built successfully.")

# 8) PRIORS - v13.
# =============================================================================
# Index for ALL vectorized tensors below (must match media_channels order):
#   0=Meta, 1=Search, 2=PMAX, 3=Amex,
#   4=Video_Epsilon, 5=Video_Google, 6=Video_Hulu, 7=Video_MNTN, 8=Video_Paramount
#
# Reading the ROI priors:
#   roi_mu    = LogNormal 'loc'   (mean in log-space)
#   roi_sigma = LogNormal 'scale' (sd in log-space)
#   prior MEDIAN ROAS = exp(loc);   prior MEAN ROAS = exp(loc + sigma^2/2)
#   95% prior CI factor around the median = exp(+/- 1.96 * sigma)
#
# Video tiers per Ken's outside view:
#   - MNTN & Epsilon: performance CTV, optimized to convert -> high ROAS prior
#   - Google:         demand-gen optimizing store visits, very strong late-2025+. Google's data is concentrated in
#                     that recent period so a bullish prior aligns with the period the model has most signal from.
#                     (See known limitation above re: low-spend extrapolation - prior is right for the run range.)
#   - Hulu:           general branding / awareness -> mid ROAS prior
#   - Paramount:      premium placement, mid-tier between branding and perf. Realized 4.6-6.2x history supports
#                     loc=1.40 (bumped from initial 1.20 branding tag).
# =============================================================================
roi_mu = tf.constant([
    1.40,   # Meta             prior mean ~4.5x
    1.35,   # Search           prior mean ~4.0x
    1.15,   # PMAX             prior mean ~3.4x
    1.15,   # Amex             prior mean ~3.4x
    1.60,   # Video_Epsilon    prior mean ~5.6x   performance CTV  (perf tier)
    1.65,   # Video_Google     prior mean ~5.9x   demand gen / store visits (perf tier)
    1.20,   # Video_Hulu       prior mean ~3.7x   general branding (brand tier)
    1.60,   # Video_MNTN       prior mean ~5.6x   performance CTV  (perf tier)
    1.40,   # Video_Paramount  prior mean ~4.6x   premium placement, mid-tier (was 1.20, realized 4.6-6.2x)
], dtype=tf.float32)

# Video sigma 0.50 (was 0.25 in v12 - too tight, posteriors collapsed onto prior with no differentiation).
# 0.50 -> 95% prior CI roughly [0.4x, 2.7x] around the median: loose enough for data to update, still informed.
roi_sigma = tf.constant([
    0.40,   # Meta
    0.28,   # Search    tight - well-measured channel; 95% mass ~2.2-6.5x
    0.45,   # PMAX
    0.45,   # Amex
    0.50,   # Video_Epsilon
    0.50,   # Video_Google
    0.50,   # Video_Hulu
    0.50,   # Video_MNTN
    0.50,   # Video_Paramount
], dtype=tf.float32)

roi_prior = tfp.distributions.LogNormal(loc=roi_mu, scale=roi_sigma)

# Adstock alpha priors (decay rate per channel).
# - Beta(2, 2) for non-video: symmetric, mean 0.5, mild prior toward moderate decay.
# - Beta(3, 2) for video: mean 0.6, biased toward slightly slower decay - video impressions typically lag
#   conversions more than search/social.
alpha_conc1 = tf.constant([2.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0], dtype=tf.float32)
alpha_conc0 = tf.constant([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0], dtype=tf.float32)
alpha_prior = tfp.distributions.Beta(concentration1=alpha_conc1, concentration0=alpha_conc0)

# Hill EC50 priors (saturation half-point, on the scaled-media axis). v13 loosened video sigmas from 0.30 -> 0.50
# to try to identify per-partner saturation. In practice the data doesn't have enough cross-spend variation to
# move ec_m off the prior mean of 1.0 - all video posteriors came back at ~1.03 +/- 0.46. No harm leaving loose.
#
# Note on the Google low-spend issue: a naive fix would be to set ec_mu[Google] lower to force earlier saturation,
# but that makes the problem WORSE - Hill marginal at x=0 is 1/ec, so lower ec means STEEPER ramp at zero and
# HIGHER implied low-spend ROAS. Setting ec higher would help with extrapolation but conflicts with observed
# high-spend saturation. The real fix is calibration, not a prior tweak.
ec_mu = tf.constant([1.0] * 9, dtype=tf.float32)
ec_sigma = tf.constant([
    0.5,   # Meta
    0.5,   # Search
    0.5,   # PMAX
    0.5,   # Amex
    0.50,  # Video_Epsilon
    0.50,  # Video_Google
    0.50,  # Video_Hulu
    0.50,  # Video_MNTN
    0.50,  # Video_Paramount
], dtype=tf.float32)
ec_prior = tfp.distributions.TruncatedNormal(loc=ec_mu, scale=ec_sigma, low=0.1, high=10.0)

prior = prior_distribution.PriorDistribution(
    roi_m=roi_prior,
    alpha_m=alpha_prior,
    ec_m=ec_prior,
)
print("v13 priors defined: tiered video means, loosened video sigmas (roi & ec).")
print("Known limitation: Google low-spend ROAS extrapolation is unreliable - trust scale-point readings only.")

# Adstock kernel family per channel.
# - geometric: classic exponential decay weight w_L = (1-alpha) * alpha^L. Peak at lag 0. Use for immediate-
#   response channels (search/social/Amex).
# - binomial: Meridian's two-parameter form allowing ramp-then-decay shapes (peak NOT at lag 0). Use for video
#   where conversions typically don't land the same week as the impression.
adstock_map = {
    "Search":          "geometric",
    "Meta":            "geometric",
    "PMAX":            "geometric",
    "Amex":            "geometric",
    "Video_Epsilon":   "binomial",
    "Video_Google":    "binomial",
    "Video_Hulu":      "binomial",
    "Video_MNTN":      "binomial",
    "Video_Paramount": "binomial",
}

# 9) Model spec.
# - media_effects_dist='log_normal': keeps channel effects positive (no negative ROI draws), matches LogNormal roi prior.
# - max_lag=12 weeks: revenue from a week's media can land up to 12 weeks later. Long enough for video's slow tail;
#   short enough to avoid spurious late-season fits.
# - hill_before_adstock=True: Hill saturation applied per-week, THEN adstock convolved over the saturated values.
#   Makes the adstock kernel shape independent of spend level (clean impulse-response interpretation), and is what
#   the decay-by-channel diagnostic step relies on.
model_spec = spec.ModelSpec(
    prior=prior,
    media_effects_dist='log_normal',
    adstock_decay_spec=adstock_map,
    max_lag=12,
    hill_before_adstock=True,
)
print("Model spec created.")

# 10) Fit model.
# - 20 chains x 3000 keep = 60k posterior draws after 1000 burn-in.
# - 3000 adapt steps tune the HMC step-size during burn-in.
# - target_accept_prob=0.85: tighter than HMC default (0.80) to reduce divergent transitions in the curvier corners
#   of the posterior (Hill + LogNormal can be funnel-shaped).
# - seed=0: reproducible chains across runs.
mmm = mmm_module.Meridian(input_data=input_data, model_spec=model_spec)
print("Meridian model initialized.")

mmm.sample_prior(500)
mmm.sample_posterior(
    n_chains=20,
    n_adapt=3000,
    n_burnin=1000,
    n_keep=3000,
    seed=0,
    dual_averaging_kwargs={'target_accept_prob': 0.85},
)
print("Posterior sampling completed.")
print("Kernel globals now set: mmm, df_bq, credentials, media_channels, media_impression_cols, "
      "media_spend_cols, non_media_cols, control_cols, out_dir.")
print("RECOMMENDED NEXT: run steps/save_model.py so this fit can be recovered without re-sampling.")
