# Drop-in replacement for the priors block in cell 0 of MMMv12.ipynb.
# Differentiates the 5 video partners based on Ken's outside knowledge:
#   - Performance/demand-gen tier (high prior ROAS):  Google, MNTN, Epsilon
#   - Branding tier            (mid prior ROAS):       Hulu, Paramount
# Sigmas loosened to 0.50 (was 0.25) so 156 weeks of national data can actually
# move the posteriors off the prior. Hill EC sigmas also loosened (0.30 -> 0.50)
# so per-partner saturation points can differentiate - critical for Google,
# which scaled 40x in 2025Q4 and clearly has a different saturation curve from
# the others.

import tensorflow as tf
import tensorflow_probability as tfp

# Index: 0=Meta, 1=Search, 2=PMAX, 3=Amex,
#        4=Video_Epsilon, 5=Video_Google, 6=Video_Hulu, 7=Video_MNTN, 8=Video_Paramount

roi_mu = tf.constant([
    1.40,  # Meta             ~4.5x
    1.35,  # Search           ~4.0x
    1.15,  # PMAX             ~3.4x
    1.15,  # Amex             ~3.4x
    1.60,  # Video_Epsilon    ~5.6x   performance CTV
    1.65,  # Video_Google     ~5.9x   demand gen / store visits - strong recent perf
    1.20,  # Video_Hulu       ~3.7x   general branding
    1.60,  # Video_MNTN       ~5.6x   performance CTV
    1.20,  # Video_Paramount  ~3.7x   general branding
], dtype=tf.float32)

roi_sigma = tf.constant([
    0.40,  # Meta
    0.28,  # Search: tight - 95% mass ~2.2-6.5x
    0.45,  # PMAX
    0.45,  # Amex
    0.50,  # Video_Epsilon    was 0.25 - too tight
    0.50,  # Video_Google
    0.50,  # Video_Hulu
    0.50,  # Video_MNTN
    0.50,  # Video_Paramount
], dtype=tf.float32)

roi_prior = tfp.distributions.LogNormal(loc=roi_mu, scale=roi_sigma)

# Adstock alpha priors - left unchanged from v12.
alpha_conc1 = tf.constant([2.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0], dtype=tf.float32)
alpha_conc0 = tf.constant([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0], dtype=tf.float32)
alpha_prior = tfp.distributions.Beta(concentration1=alpha_conc1, concentration0=alpha_conc0)

# Hill EC50 - loosened video sigmas (0.30 -> 0.50) so the per-partner
# saturation point can identify from data. This is the bigger fix for Google.
ec_mu = tf.constant([1.0] * 9, dtype=tf.float32)
ec_sigma = tf.constant([
    0.5, 0.5, 0.5, 0.5,
    0.50, 0.50, 0.50, 0.50, 0.50,
], dtype=tf.float32)
ec_prior = tfp.distributions.TruncatedNormal(loc=ec_mu, scale=ec_sigma, low=0.1, high=10.0)
