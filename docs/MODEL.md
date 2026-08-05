# Model card — ABC MMM v13

The authoritative definition is the code + comments in `steps/01_fit_model.py`.
This page is the narrative companion: what the model is, why the priors look the way
they do, what each analysis means, and where it's known to be weak.

## Data

| | |
|---|---|
| Source | BigQuery view `donut-426.abc.mmm` (the weekly "blender" view: media + promos + controls) |
| Filter | `Model_Dates = 'In Model'` (excludes burn-in / hold-out weeks) |
| Granularity | Weekly, national (single geo `national_geo`; Meridian enforces `aggregate_geos=True` — the warning is expected) |
| KPI | `Conversions_Revenue`, continuous dollars (`kpi_type='revenue'`) |
| History | ~174 weeks in-model (~2023 → mid-2026); ~156 weeks informed the v13 prior-width decisions |

## Channels

Order is load-bearing: prior tensors map to channels **by index**. Never reorder one
list without all of them.

| # | Channel | Activity metric | Adstock | ROI prior LogNormal(loc, σ) | Prior mean ROAS | Tier rationale |
|---|---------|----------------|---------|------------------------------|-----------------|----------------|
| 0 | Meta | impressions | geometric | (1.40, 0.40) | ~4.5x | |
| 1 | Search | **clicks** | geometric | (1.35, 0.28) | ~4.0x | tight σ — well-measured channel |
| 2 | PMAX | impressions | geometric | (1.15, 0.45) | ~3.4x | |
| 3 | Amex | impressions | geometric | (1.15, 0.45) | ~3.4x | |
| 4 | Video_Epsilon | impressions | binomial | (1.60, 0.50) | ~5.6x | performance CTV (perf tier) |
| 5 | Video_Google | impressions | binomial | (1.65, 0.50) | ~5.9x | demand-gen / store visits (perf tier) |
| 6 | Video_Hulu | impressions | binomial | (1.20, 0.50) | ~3.7x | general branding (brand tier) |
| 7 | Video_MNTN | impressions | binomial | (1.60, 0.50) | ~5.6x | performance CTV (perf tier) |
| 8 | Video_Paramount | impressions | binomial | (1.40, 0.50) | ~4.6x | premium placement; was 1.20, bumped after realized 4.6–6.2x history |

Reading LogNormal ROI priors: median ROAS = `exp(loc)`; mean = `exp(loc + σ²/2)`;
95% prior CI factor = `exp(±1.96σ)`. Video σ = 0.50 ⇒ roughly [0.4x, 2.7x] around the median.

**Other treatment variables** (linear, no Hill/adstock):

- Non-media treatments: `Vault_Drops`, `Email_sends`, `Redemptions_Other`, `StoreCount`
- Controls: `Category_Interest`, `Hurricanes`, `LightningSales`,
  `Redemptions_Birthday_Signup`, `Celebs`
  (Redemptions split Birthday/Signup vs Other so the structurally-elevated birthday-signup
  baseline doesn't wash out general redemption signal.)

## Other priors

- **Adstock α**: Beta(2,2) non-video (mean .5), Beta(3,2) video (mean .6 — slower decay;
  video conversions lag impressions).
- **Hill EC50**: TruncatedNormal(1.0, 0.5, low=0.1, high=10) all channels. v13 loosened
  video σ hoping to identify per-partner saturation; posteriors stayed ≈ prior (not
  enough cross-spend variation) — harmless, left loose.

## Model spec & sampling

- `media_effects_dist='log_normal'` — **inert for this model**: Meridian resets it to
  `'normal'` in nationally aggregated models (UserWarning observed on the first local
  run, meridian 1.7.1; equally true of the Colab runs). Kept in the spec for fidelity
  to the notebook and in case the model ever goes geo-level.
- `max_lag=12` weeks — long enough for video tails, short enough to avoid spurious
  late-season fits.
- `hill_before_adstock=True` — saturation per-week, then adstock convolution. Makes the
  adstock kernel spend-level-independent; the decay analysis (step 04) **depends** on this.
- Adstock family: geometric (Search/Meta/PMAX/Amex — peak at lag 0) vs binomial (all
  video — allows ramp-then-decay, peak after lag 0).
- Sampling: 20 chains × (3000 adapt, 1000 burn-in, 3000 keep) = 60k posterior draws,
  `target_accept_prob=0.85` (curvy Hill+LogNormal posterior), `seed=0` (reproducible).

## Fit quality (v13 reference points)

- Full ~174-week window: R² ≈ 0.71 — dragged down by 2023/early-2024 when several video
  partners weren't active.
- Last 52 weeks: R² ≈ 0.82 — the window budget decisions actually rely on. Step 05
  appends a "Last 52 Weeks" row to the dashboard's ModelDiagnostics tab for exactly
  this reason (classical R², typically within 1–2 pts of Meridian's Bayesian R²).
- Convergence gate: `r_hat < 1.05` on `roi_m`, `beta_m`, `beta_gm`, `ec_m` (step 02
  prints the table; charts saved to Drive under `diagnostics/<stamp>/`).

## Known limitations (do not skip)

1. **Google low-spend ROAS extrapolation is unreliable.** At ~$9k/qtr Google spend the
   model reads 20–30x aligned ROAS; at $217k (2025Q4) a credible 2.3x. The low-spend
   number is the Hill curve passing through near-zero data, not a measurement (Hill with
   slope 1 has marginal response 1/ec at x=0; fitting high-spend saturation + low-spend
   revenue forces low ec / high beta, inflating the extrapolation). **Trust Google ROAS
   only near actually-run spend levels (~$10k–$220k/qtr).** The scenario planner WILL
   recommend cutting Google to ~$10k/qtr at 30x — do not take that at face value.
   Real fix: YouTube holdout / incrementality test to calibrate `roi_m[Video_Google]`.
   No prior tweak solves this (lower ec makes it worse; higher ec fights observed
   saturation).
2. **Spend-aligned ROAS is tail-truncated at the end of the window.** Quarters whose
   weeks fall within `max_lag` (12) weeks of the data end have part of their revenue tail
   beyond the data; rows are flagged `tail_truncated=True` and understate true ROAS.
3. **Controls are not attributable.** Meridian's analyzer doesn't decompose controls
   (Hurricanes, Category_Interest, LightningSales, Redemptions_Birthday_Signup, Celebs)
   through `incremental_outcome` — they're absorbed into the fit. Possible future
   extension: compute `gamma_c * X_c` per quarter from the posterior manually.
4. **Video EC50s are prior-driven.** All video `ec_m` posteriors ≈ 1.03 ± 0.46 (the
   prior). Per-partner saturation points are not identified by current data.

## The analyses

- **Step 02 — HTML results summary**: Meridian's standard two-pager over the report
  window (currently 2025-06-29 → 2026-06-21; must span 52/53 week-starts). The
  main client-facing artifact.
- **Step 03 — spend-aligned ROAS by quarter**: default "realized" ROAS (revenue landing
  in Q ÷ spend in Q) is distorted by adstock lag; this analysis turns media ON only for
  quarter Q (`media_selected_times`) and pulls the full downstream revenue tail back to
  Q. Reports both views side-by-side plus non-media treatment attribution
  (linear ⇒ realized = aligned). 90% CI columns when `WITH_CI=True`.
- **Step 04 — adstock decay profiles**: per channel, one impulse-week counterfactual
  recovers the adstock kernel directly (valid because `hill_before_adstock=True`);
  reports % of revenue by lag week, half-life, weeks-to-90%. Expect ~52% of revenue in
  week 0 for geometric channels vs ~14% for video.
- **Step 05 — scenario planner**: builds Meridian UI protos (model fit, marketing
  analysis, budget optimization with ±40% per-channel spend shift, yearly buckets,
  optimization name "ABC FY26") and writes worksheets **into the existing dashboard
  spreadsheet** (`101EYa2FK8BJ4u6SCC4cyDvgYuWrdnP2fSaHWRk0IfVU`) so Looker Studio
  refreshes automatically. Two custom augmentations on the gspread path:
  "Last 52 Weeks" diagnostics row, and a `MediaROI_Aligned` tab (spend-aligned ROI,
  schema-parallel to `MediaROI` for one-click Looker repointing).

## Outputs in Drive (`My Drive/ABC/MMM/`)

| Pattern | Producer |
|---|---|
| `v13_summary_output_<start>_to_<end>_<stamp>.html` | step 02 |
| `diagnostics/<stamp>/*.html`, `*.png` | step 02 (new in CLI migration) |
| `roas_by_quarter_spend_aligned_<stamp>.csv` | step 03 |
| `decay_profile_by_channel_<stamp>.csv`, `decay_summary_by_channel_<stamp>.csv` | step 04 |
| `decay_profile_plot_<stamp>.png` | step 04 (new in CLI migration) |
| `model_saves/mmm_v13_<stamp>.binpb` (`.pkl` from older Meridian builds) | save_model (new in CLI migration) |
| dashboard spreadsheet worksheets | step 05 |

Historical v10/v12 HTML files in the same folder predate this repo.
