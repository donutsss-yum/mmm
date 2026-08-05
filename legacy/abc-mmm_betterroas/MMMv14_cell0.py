# @title MMMv14 - Paramount re-tiered to premium + tightened video CIs

# =============================================================================
# CHANGES FROM v13:
# - Paramount: roi_mu 1.20 -> 1.55 (prior mean 3.7x -> 5.0x). Re-classified
#   from "branding" to "premium placement" per Ken's update. Realized aligned
#   ROAS history 4.6-6.2x across 5 quarters supports this; the branding tag
#   was holding the posterior down (v13 was 4.55 against a 3.76 prior mean).
# - All video roi_sigma: 0.50 -> 0.35. v13 posteriors confirmed the prior
#   centers are correctly positioned and the rank order matches Ken's
#   outside view (MNTN > Google > Epsilon > Paramount > Hulu). With that
#   confirmation, we can express more confidence. 0.35 -> 95% prior CI
#   factor roughly [0.5x, 2.0x] around the median.
# - ec_sigma unchanged. v13 ec_m posteriors had zero signal from data (all
#   clustered at 1.0 +/- 0.46) - the saturation point is genuinely
#   unidentified, tightening would give false precision.
#
# CHANGES FROM v12 (carried forward from v13):
# - non_media_cols: removed Conversions_BasketSize and Conversions_Pricing.
# - roi_mu for video: per-partner tiered priors (was uniform 1.65 x 5).
# - roi_sigma for video: loosened from 0.25 to allow data to differentiate.
# - ec_sigma for video: loosened from 0.30 to allow saturation identification
#   (didn't end up panning out empirically, but no harm leaving loose).
# =============================================================================

# 1) Install dependencies (colab + scenarioplanner + cuda - all in one pip call)
!pip -q install --upgrade google-meridian[colab,scenarioplanner,and-cuda]

# 2) Authenticate BigQuery + Drive + Sheets in one popup; mount Drive
from google.colab import auth, drive
import datetime

credentials = auth.authenticate_user([
    'https://www.googleapis.com/auth/bigquery',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
])
drive.mount('/content/drive')

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
print("GPU Available:", len(tf.config.list_physical_devices('GPU')) > 0)
print("TensorFlow version:", tf.__version__)

# 5) Pull data from BigQuery.
#    abc.mmm is the weekly blender view (media + promos + controls).
#    'In Model' filter excludes weeks we don't want to fit (burn-in, hold-outs).
project_id = 'donut-426'
view_sql = """SELECT * FROM abc.mmm WHERE Model_Dates = 'In Model'"""

df_bq = pandas_gbq.read_gbq(view_sql, project_id=project_id)
if 'time' not in df_bq.columns:
    raise ValueError("Expected a 'time' column in BigQuery data.")
df_bq['time'] = pd.to_datetime(df_bq['time'])

# 6) Channel / variable definitions.
#    CRITICAL: media_channels order must match media_impression_cols and
#    media_spend_cols index-for-index, AND must match the vectorized priors
#    below (roi_mu[i] applies to media_channels[i]). Don't reorder these lists
#    without also reordering the prior tensors.
media_channels = ['Meta', 'Search', 'PMAX', 'Amex',
                  'Video_Epsilon', 'Video_Google', 'Video_Hulu',
                  'Video_MNTN', 'Video_Paramount']

# Per-channel media-activity metric. Note Search uses CLICKS, everything else
# (including Amex) uses IMPRESSIONS. This list is parallel to media_channels.
media_impression_cols = ['Meta_impression', 'Search_click', 'PMAX_impression', 'Amex_impression',
                         'Video_Epsilon_impression', 'Video_Google_impression', 'Video_Hulu_impression',
                         'Video_MNTN_impression', 'Video_Paramount_impression']

media_spend_cols = [f"{ch}_spend" for ch in media_channels]

# Non-media treatments enter the model linearly (no Hill/adstock).
# v13: removed Conversions_BasketSize and Conversions_Pricing - they were
# confounding the fit (capturing demand-side variation media should explain).
non_media_cols = ['Vault_Drops', 'Email_sends', 'StoreCount', 'Celebs']

# Controls also enter linearly. Redemptions split into Birthday/Signup vs Other
# so the structurally-elevated Birthday signup baseline doesn't wash out
# general redemption signal.
control_cols = ['Category_Interest', 'Hurricanes', 'LightningSales',
                'Redemptions_Other', 'Redemptions_Birthday_Signup']

population_col = 'population' if 'population' in df_bq.columns else None

required_cols = (['time', 'geo', 'Conversions_Revenue']
                 + media_impression_cols + media_spend_cols
                 + non_media_cols + control_cols)
missing = [c for c in required_cols if c not in df_bq.columns]
if missing:
    raise ValueError(f"Missing columns: {missing}. Verify your BigQuery schema.")
print("All key columns present. Shape:", df_bq.shape)

# 7) Build Meridian InputData.
#    KPI is revenue (continuous, dollars). Builder needs a 'geo' column; for a
#    national model this has a single value ('national_geo') and Meridian
#    warns later that aggregate_geos=True is enforced - that's expected.
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

# 8) PRIORS - v14.
# =============================================================================
# Index for ALL vectorized tensors below (must match media_channels order):
#   0=Meta, 1=Search, 2=PMAX, 3=Amex,
#   4=Video_Epsilon, 5=Video_Google, 6=Video_Hulu, 7=Video_MNTN, 8=Video_Paramount
#
# Reading the ROI priors:
#   roi_mu    = LogNormal 'loc' (mean in log-space)
#   roi_sigma = LogNormal 'scale' (sd in log-space)
#   prior MEDIAN ROAS = exp(loc)
#   prior MEAN   ROAS = exp(loc + sigma^2/2)
#   95% prior CI factor around the median = exp(+/- 1.96 * sigma)
#
# Video tiering (Ken's outside view, refined by v13 posteriors):
#   - Performance CTV (high prior ROAS):  MNTN, Epsilon - optimized to convert
#   - Demand-gen high tier:                Google - store-visit demand gen,
#                                          strong recent-period performance
#   - PREMIUM placement (mid-high tier):   Paramount - premium inventory, sits
#                                          between branding and perf tiers.
#                                          v13 realized history 4.6-6.2x supports
#                                          this; was mis-tagged as branding in v13.
#   - Branding / awareness (mid tier):     Hulu - general awareness
# =============================================================================
roi_mu = tf.constant([
    1.40,   # Meta             prior mean ~4.5x   (sigma 0.40)
    1.35,   # Search           prior mean ~4.0x   (sigma 0.28)
    1.15,   # PMAX             prior mean ~3.4x   (sigma 0.45)
    1.15,   # Amex             prior mean ~3.4x   (sigma 0.45)
    1.60,   # Video_Epsilon    prior mean ~5.3x   performance CTV (perf tier)
    1.65,   # Video_Google     prior mean ~5.5x   demand gen / store visits (perf tier)
    1.20,   # Video_Hulu       prior mean ~3.5x   general branding (brand tier)
    1.60,   # Video_MNTN       prior mean ~5.3x   performance CTV (perf tier)
    1.55,   # Video_Paramount  prior mean ~5.0x   PREMIUM placement (v14: was 1.20
            #                                       branding; realized history
            #                                       4.6-6.2x and team confirms
            #                                       premium status - sits between
            #                                       branding and perf tiers)
], dtype=tf.float32)

roi_sigma = tf.constant([
    0.40,   # Meta
    0.28,   # Search    tight - well-measured channel; 95% mass ~2.2-6.5x
    0.45,   # PMAX
    0.45,   # Amex
    0.35,   # Video_Epsilon    v14: 0.50 -> 0.35. v13 posteriors confirmed
    0.35,   # Video_Google     priors are correctly positioned and rank order
    0.35,   # Video_Hulu       matches outside view; expressing more confidence.
    0.35,   # Video_MNTN       95% prior CI factor ~ [0.5x, 2.0x] around median.
    0.35,   # Video_Paramount
], dtype=tf.float32)

roi_prior = tfp.distributions.LogNormal(loc=roi_mu, scale=roi_sigma)

# Adstock alpha priors (decay rate per channel).
# - Beta(2, 2) for non-video: symmetric, mean 0.5, mild prior toward moderate
#   decay.
# - Beta(3, 2) for video: mean 0.6, biased toward slightly slower decay -
#   video impressions typically lag conversions more than search/social.
alpha_conc1 = tf.constant([2.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0], dtype=tf.float32)
alpha_conc0 = tf.constant([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0], dtype=tf.float32)
alpha_prior = tfp.distributions.Beta(concentration1=alpha_conc1, concentration0=alpha_conc0)

# Hill EC50 priors (the saturation half-point, on the scaled-media axis).
# v13 loosens video sigmas from 0.30 -> 0.50 so per-partner saturation can
# identify from data. Mean of 1.0 stays - it's a reasonable scale-aware default
# (the data is scaled to have mean 1.0). The bigger fix is letting sigma move.
ec_mu = tf.constant([1.0] * 9, dtype=tf.float32)
ec_sigma = tf.constant([
    0.5,   # Meta
    0.5,   # Search
    0.5,   # PMAX
    0.5,   # Amex
    0.50,  # Video_Epsilon    was 0.30 in v12
    0.50,  # Video_Google     CRITICAL - Google scaled 40x in 2025Q4, needs its
    0.50,  # Video_Hulu       own ec_m to capture saturation
    0.50,  # Video_MNTN
    0.50,  # Video_Paramount
], dtype=tf.float32)
ec_prior = tfp.distributions.TruncatedNormal(loc=ec_mu, scale=ec_sigma, low=0.1, high=10.0)

prior = prior_distribution.PriorDistribution(
    roi_m=roi_prior,
    alpha_m=alpha_prior,
    ec_m=ec_prior,
)
print("v14 priors defined: Paramount re-tiered to premium, video sigmas tightened.")

# Adstock kernel family per channel.
# - geometric: classic exponential decay weight w_L = (1-alpha) * alpha^L. Peak
#   at lag 0. Use for immediate-response channels (search/social/Amex).
# - binomial: Meridian's two-parameter form that allows ramp-then-decay shapes
#   (peak NOT at lag 0). Use for video where conversions typically don't land
#   the same week as the impression.
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
# - media_effects_dist='log_normal': keeps channel effects positive (no negative
#   ROI draws), matching the LogNormal roi_m prior.
# - max_lag=12 weeks: revenue from a week's media can land up to 12 weeks later.
#   Long enough for video's slow tail; short enough to avoid spurious late-
#   season fits.
# - hill_before_adstock=True: Hill saturation applied per-week, THEN adstock
#   convolved over the saturated values. Makes the adstock kernel shape
#   independent of spend level (clean impulse-response interpretation), and is
#   what the decay-by-channel diagnostic cell relies on.
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
# - 3000 adapt steps: tunes the HMC step-size during burn-in.
# - target_accept_prob=0.85: tighter than HMC default (0.80) to reduce divergent
#   transitions in the curvier corners of the posterior (Hill + LogNormal can
#   be funnel-shaped).
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
