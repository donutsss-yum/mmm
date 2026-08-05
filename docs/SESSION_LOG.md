# Session log

Newest first. One entry per meaningful working session: what was done, what was
decided, what's pending. Keep `CLAUDE.md`'s "Current status" in sync.

## 2026-08-05 (v14 experiment built) — exp/v14-revenue-split branch [THIS BRANCH]

Ken applied the extended view to BigQuery. This branch carries the split-model
experiment; `main` remains the production v13.

- `steps/10_exp_fit_split.py`: hard gates (split columns present; weekly
  reconciliation |total − ΣSplits| ≤ $1), then fits THREE models with the same
  26-week holdout (`ModelSpec.holdout_id` — KPI excluded from likelihood, media
  still drives adstock; verified against meridian v1.7.1 source):
  T=total (v13 priors, refit so the comparison is fair), S=InStore, D=Digital
  (Ecom+App+Vault). Sub-model priors = v13 medians × revenue share
  (loc + ln share), sigmas widened +0.15 for allocation uncertainty.
- `steps/11_exp_scorecard.py`: holdout R²/MAPE/wMAPE of pred(S)+pred(D) vs
  pred(T) against actual total (posterior-mean weekly `expected_outcome`);
  per-channel double-count check (split vs baseline incremental, flag ratios
  outside [0.8, 1.25]); convergence gate (max r_hat < 1.05). Prints a verdict,
  exports two stamped CSVs. Promote only if split wins holdout AND passes gates.
- Stage maps in run_local.py / run_pipeline.sh / export_notebook.py gained
  stages 10/11 (notebook export works for the experiment per Ken's requirement).
- To run:  `caffeinate -i .venv/bin/python scripts/run_local.py 00 10 11`
  (~15 min local: 3 × ~4-min fits + scorecard).

## 2026-08-05 (later still) — View SQL versioned in git + extended with revenue splits

Confirmed the splits are NOT yet in the weekly view (44 cols, only total
`Conversions_Revenue`), then pulled the full view definition. Structure: 9-block
UNION ALL blender (media, revenue via `abc.gSheet_rev`, vault drops, gtrends, email,
lightning, storecount, celebs, promos) → weekly GROUP BY. `abc.gSheet_rev` is the
Sheets-backed table over the daily revenue tab, so the split columns were already
reachable — the view just never selected them.

- **`sql/abc_mmm_view.sql` is now the versioned source of truth** for the view
  (CREATE OR REPLACE VIEW; previously BigQuery-only). Change process: edit in git →
  commit → apply to BQ.
- Added `Conversions_Revenue_InStore / _Ecom / _App / _Vault` (weekly sums; NULL
  placeholders in all 9 union blocks since UNION ALL is positional). Non-breaking
  for v13 (columns selected by name).
- Apply gates: (1) pre-check that `abc.gSheet_rev` exposes Rev_InStore/Ecom/App/Vault
  to BQ (external-table schema may lag the sheet); (2) post-apply reconciliation —
  the four splits must sum to Conversions_Revenue every in-model week. Queries in
  the 2026-08-05 chat / re-derivable trivially.
- Side facts recorded: geo constant is `'FL'`; view carries unused-by-model columns
  (Video_Peacock_*, Email_spend, Video_* aggregates); `Model_Dates` in-model window
  is 2023-01-01 → 2026-06-27, rolled forward manually on refresh (Ken's comment
  preserved in the SQL).

## 2026-08-05 (late night) — Revenue-split experiment scoped; notebook exporter added

Ken proposed splitting the model by revenue stream and summing outputs. Scouting
findings (from the "ABC MMM Inputs" sheet, read via Drive):

- The split EXISTS as daily columns in the Inputs sheet: `Rev_All / Rev_InStore /
  Rev_Ecom / Rev_App / Rev_Vault` (+ Trans_*/Units_* each), daily from 2023-01-01.
- **Proportions matter**: InStore ≈ 95–98% of revenue; App and Vault are structurally
  ZERO until their launches (App well into the history; Vault ~Aug 2024). A 4-model
  split is therefore ill-posed (tiny/partial KPIs fitting 9 channels; Vault revenue is
  drop-driven — Vault_Drops is already a model treatment). **Agreed direction: start
  2-way — InStore vs Digital (Ecom+App+Vault)** — as `exp/v14-revenue-split`, scored
  on a ~26-week holdout of summed predictions vs the single-model baseline, plus a
  double-counting check (summed channel attribution vs baseline's).
- Open item before building: confirm whether weekly split columns already exist in
  the `abc.mmm` view (`SELECT * LIMIT 1` and eyeball columns) or whether the view
  needs extending from the daily raw tab.
- NEW TOOLING: `scripts/export_notebook.py` — exports any branch's pipeline as a
  Colab-web-runnable .ipynb (provenance markdown cell + setup cell with
  pip/auth/drive.mount + verbatim step cells; nbformat-validated). Ken's requirement:
  every experiment must be runnable "the old fashioned way". Output gitignored under
  notebooks/exports/. Conventions documented in WORKFLOW.md (+ `exp/` branch rule).

## 2026-08-05 (night) — FIRST END-TO-END RUN: local backend, full success

`caffeinate -i .venv/bin/python scripts/run_local.py` on Ken's MBP (Apple silicon,
CPU-only, TF 2.20 + XLA, google-meridian 1.7.1). **Total pipeline: 366 s.**

| Stage | Wall clock | Notes |
|---|---|---|
| 00 preflight | 5 s (59 s cold) | cold run pays TF import |
| 01 fit | **226 s** | **beats the ~8 min A100 baseline** — national model is small; XLA CPU + 20 chains parallelize fine. Data shape (182, 44). |
| save | 1 s | 70 MB `.binpb` via new serde path — worked first try |
| 02 diagnostics + HTML | 110 s | all charts saved (Altair HTML + PNG); no chart-save wrinkles |
| 03 ROAS quarterly | 17 s | CSV exported |
| 04 decay profiles | 7 s | CSVs + PNG exported |

**Fit quality:** every `r_hat` = 1.0 (roi_m, beta_m, beta_gm, ec_m). Posteriors match
v13's documented behavior: Search 4.1x, Meta 4.9x, MNTN 6.4x / Paramount 6.2x (above
prior, consistent with realized history), Google 5.9x ≈ prior (documented
can't-move-it case), all ec_m ≈ 1.0. Decay fingerprint reproduced: ~51–53% wk-0 for
geometric channels, ~14% wk-0 / half-life 4 wk for video.

**Consequence:** local is now the default backend for EVERYTHING except stage 05
(cost locally still unmeasured). Colab's remaining role: stage 05 (if slow locally)
and nothing else, pending that measurement.

**Observations for future maintenance:**
- Meridian warns `media_effects_dist will be reset to 'normal'` — national models
  ignore the spec's `log_normal`; setting is inert (true on Colab too). MODEL.md updated.
- `Analyzer(mmm)` DeprecationWarning: `meridian` arg → `model_context` in a future
  Meridian; steps 03/04 will need a one-line change eventually.
- Benign/cosmetic: population ignored (national), revenue_per_kpi ignored,
  eta/xi/tau params forced Deterministic(0) (national), arviz "trace group" warnings,
  tqdm missing (added to requirements-local.txt for fresh setups).

## 2026-08-05 (evening) — First machine setup; ADC scope reality, in two acts

Ken began first local setup on his MBP. Field findings folded into docs:

- **Act 1**: Google **blocked** the ADC login when it included `drive` +
  `spreadsheets` ("This app is blocked" — Workspace restricts sensitive scopes for
  unconfigured apps). We initially dropped those scopes, reasoning steps 00–04 didn't
  need them (local outputs are plain files in the synced Drive folder).
- **Act 2 — wrong**: first real run failed in step 01: BigQuery returned
  `403 ... Permission denied while getting Drive credentials`. **The `abc.mmm` view
  reads a Google-Sheets-backed external table** (the "ABC MMM Inputs" sheet), so
  EVERY query against it needs Drive-scoped credentials. Colab never surfaced this
  because `colab auth` grants Drive access. Consequence: the Workspace allow-list of
  the gcloud OAuth client is **mandatory setup** (SETUP.md § 3a), followed by the
  full 6-scope ADC login (§ 3b). Silver lining: stage 05 locally is unlocked by the
  same fix. Preflight (step 00) now probes `abc.mmm` itself instead of `SELECT 1`,
  with a targeted remediation message for the Drive-credentials failure.
- Also: `main` now exists and should be the default branch (repo started empty, so
  the migration branch was the only/default branch and PR creation failed with
  "resource not found" — no base branch. Ken chose promote-to-main over a PR).

## 2026-08-05 (later still) — Adversarial verification pass applied

Ran an 8-auditor verification workflow (cell-by-cell notebook parity, real-CLI flag
audit, macOS bash 3.2 portability, docs-vs-code consistency, new-API checks against
upstream Meridian). 13 findings, all fixed:

- **Notebook bug surfaced (worth knowing):** cell 2's comment and `non_media_agg`
  named `Celebs` as a non-media treatment, but the model's treatments are
  `[Vault_Drops, Email_sends, Redemptions_Other, StoreCount]` (`Celebs` is a control).
  The `'Celebs'` agg entry was dead code and `Redemptions_Other` silently fell back to
  'sum'. Step 03 now states the true lists and aggregates `Redemptions_Other: 'sum'`
  explicitly — numerically identical results, honest config. This bug exists in the
  archived notebook too (left as-is there; it's a frozen copy).
- `save_mmm`/`load_mmm` are **deprecated** in Meridian v1.7.1 → save/load now prefer
  `meridian.schema.serde.meridian_serde.save_meridian`/`load_meridian` (protobuf
  `.binpb`, cross-version safe) with pickle fallback for older builds; loader accepts
  both formats.
- load_model now *prints* the stale-fit-vs-fresh-data caution (was comment-only).
- Step 04 no longer flips the kernel-wide matplotlib backend (fig.savefig doesn't
  need it); step 02 still does and now documents the side effect.
- Step 05: globals check extended to df_bq/media_channels/media_spend_cols (used on
  the gspread path); runtime-estimate strings harmonized (~1.5 h A100) and documented.
- Doc drift from the local-backend edits corrected (preflight success string, scope
  count, error-message strings, timeout-table pointer, MIGRATION NOTE claims,
  `.binpb` in output table); `setup_local.sh` executable bit committed.

## 2026-08-05 (later) — Local execution backend added

Ken: "not even sure we need Colab — my MBP has a shit ton of RAM — set up the code to
run locally." Done, as a SECOND backend rather than a replacement (RAM was never the
constraint for this small national model; sampler speed is, and the A100 stays useful
for the ~1.5 h scenario planner):

- `scripts/run_local.py` — runs stages in ONE shared Python namespace (the local twin
  of the Colab kernel). Sets `MMM_ALLOW_CPU=1`; `--out-dir` / `--require-gpu` flags.
- `scripts/setup_local.sh` + `requirements-local.txt` — `.venv` (Python 3.12 via uv),
  Meridian **without** the CUDA extra (TF CPU wheel; no NVIDIA GPU on a Mac).
- Steps made environment-aware: `out_dir` resolves env-var → Colab mount → desktop-
  synced Drive folder (`~/Library/CloudStorage/GoogleDrive-ken@donutanalytics.com/My
  Drive/ABC/MMM`); auth-failure remediation messages differ per environment; step 00
  treats missing GPU as WARN locally / FAIL on Colab.
- SETUP.md § 3 now mints ADC with the union scope set (colab + drive + spreadsheets)
  so one login serves both backends. docs/LOCAL.md added (tradeoffs, first-run watch
  list, tensorflow-metal caveat).

Open question for first local run: **wall-clock of the CPU fit** (record it here).
If it's tolerable, local becomes the everyday path and Colab is reserved for stage 05
and deadline days. tensorflow-metal deliberately NOT installed (TFP-on-Metal is
unreliable for MCMC; try only against a verified CPU baseline).

## 2026-08-05 — Migration: Colab web UI → git + Colab CLI (Claude Code session)

**Done:**

- Created this repo from `MMMv13_2.ipynb` (the v13 model, previously run by pasting
  cells into the Colab web UI). The 5 notebook cells became `steps/01–05`; steps
  `00_check_runtime.py`, `save_model.py`, and `load_model.py` are new additions with
  no notebook source. Each migrated step (01–05) carries a MIGRATION NOTE header
  documenting exactly what changed vs. its source cell.
- Deliberate changes vs. the notebook (everything else is 1:1):
  - `!pip install` → `requirements-colab.txt` + `colab install` (provision.sh).
  - `google.colab.auth.authenticate_user(...)` + `drive.mount(...)` → ADC via
    `google.auth.default()`, with `colab auth` / `colab drivemount` as the interactive
    per-session setup.
  - Inline chart display → files: step 02 saves Altair charts as HTML + ArviZ plots as
    PNG under `diagnostics/<stamp>/` on Drive; step 04 saves its decay plot as PNG.
  - Cell 1's trailing duplicate `plot_rhat_boxplot()` display dropped (redundant in a
    non-display context).
  - Cell 4's `@param` Colab-form annotations dropped (plain variables now); its inline
    `!pip` re-install replaced by an import check with remediation message.
  - NEW: model persistence (`save_model.py` / `load_model.py`) so a fit survives VM
    resets — previously a runtime reset forced a full re-fit.
  - NEW: preflight (`00_check_runtime.py`) validating GPU/deps/auth/Drive/BQ before
    burning GPU time.
- Validated the `colab` CLI (v0.6.0) hands-on in the dev container: command surface,
  `exec --timeout` default of 30s (!), kernel-state persistence, interactive-only
  commands, ADC scope requirements. Runner scripts encode all of it.
- Wrote the documentation set: CLAUDE.md, README, docs/{SETUP,WORKFLOW,MODEL,CHANGELOG}.

**Decided:**

- Stage 05 (scenario planner) is excluded from the default pipeline — it overwrites the
  live dashboard sheet and takes ~1.5 h; explicit invocation only.
- Session name convention: `mmm`. Default GPU: A100.
- Outputs stay on Drive (`My Drive/ABC/MMM/`), NOT in git; the repo holds code + docs.

**Pending / first-run watch list:**

- Nothing has executed end-to-end via the CLI yet (needs Ken's one-time setup:
  docs/SETUP.md — CLI install + gcloud ADC scopes; then per-session `colab auth` +
  `colab drivemount`).
- Watch on first run: (a) Altair `chart.save()` in step 02 may need a JS-engine
  fallback — failures are caught per-chart and printed, the HTML summary is unaffected;
  (b) whether ADC on the VM carries Sheets scope for gspread in step 05 — fallback
  path + clear error in place; (c) confirm `colab exec --timeout` behavior on very long
  stages (05) — if the exec client disconnects while the kernel keeps computing, use
  `colab status` / `colab log` to monitor, and consider `colab run` for 05 in future.
