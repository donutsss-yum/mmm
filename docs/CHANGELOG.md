# Changelog

Model versions newest-first. Infrastructure changes are logged in
[SESSION_LOG.md](SESSION_LOG.md); this file is for **model** changes.

## v13 (current) — differentiated video priors

- `non_media_cols`: removed `Conversions_BasketSize` and `Conversions_Pricing` —
  they were confounding the fit (capturing demand-side variation media should explain).
- Video ROI priors: from a uniform `loc=1.65 × 5` to per-partner tiers based on Ken's
  outside view of inventory type:
  - Performance / demand-gen tier (high prior ROAS): Video_Google 1.65, Video_MNTN 1.60,
    Video_Epsilon 1.60
  - Branding / awareness tier (mid prior ROAS): Video_Hulu 1.20, Video_Paramount 1.20
  - Video_Paramount later bumped 1.20 → **1.40** after realized history showed
    consistent 4.6–6.2x ROAS.
- Video `roi_sigma`: 0.25 → **0.50**. The old 0.25 was so tight that v12 video
  posteriors all collapsed to ~5.3–5.7x (still on the prior); 0.50 lets 156 weeks of
  national data actually move them.
- Video `ec_sigma`: 0.30 → **0.50** to try to identify per-partner Hill saturation.
  Empirically didn't pan out (all video ec_m posteriors stayed ≈ prior mean 1.0);
  left loose, no harm.
- Scenario planner: now writes into the **existing** dashboard spreadsheet
  (fixed ID) instead of creating a new sheet each run; added "Last 52 Weeks"
  diagnostics row and `MediaROI_Aligned` tab.

Known-and-accepted at v13: Google low-spend ROAS extrapolation unreliable
(see MODEL.md, limitation #1).

## v12 — uniform video priors

- Single ROI prior for all five video partners: LogNormal(1.65, 0.25).
- Result that motivated v13: video posteriors indistinguishable (~5.3–5.7x),
  i.e. the prior was doing all the talking.

## The unadopted "v14 draft" (May–June 2026, legacy/abc-mmm_betterroas/MMMv14_cell0.py)

A notebook-era draft that never shipped: Paramount roi_mu 1.20 → 1.55 ("premium
placement" re-tier) and ALL video roi_sigma tightened 0.50 → 0.35. What actually
happened: v13 adopted the Paramount re-tier at a compromise 1.40, and the sigma
tightening was dropped. The 2026-08-05 v15 experiment retroactively vindicated that
call — video posteriors are prior-driven at any aggregation, so sigma 0.35 would have
manufactured false precision. (Note: this legacy "v14" is unrelated to the 2026-08-05
`exp/v14-revenue-split` experiment; version numbers restarted with the git-era
experiments.)

## v10–v12 (Colab-notebook era, artifacts in legacy/)

- **v10** (`legacy/abc-mmm/mmmv10.py`): vectorized priors; Celebs added as a test
  control. Client HTML exports survive in Drive (e.g. `..._v10.4.html`).
- **v12** (`legacy/abc-mmm_improvefit/mmmv12.py`, `legacy/abc-mmm_betterroas/MMMv12.ipynb`):
  "the spec that works" — scenarioplanner extra added; uniform video ROI priors
  LogNormal(1.65, 0.25); the fit-improvement work in `abc-mmm_improvefit` fed the v13
  changes. Development outputs (spend-aligned ROAS iterations, decay profiles,
  May 2026 summary HTML) preserved in `legacy/abc-mmm_betterroas/`.
