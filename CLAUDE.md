# CLAUDE.md — ABC Media Mix Model (Meridian on Colab GPU via the Colab CLI)

Read this first in every session. Deeper detail lives in `docs/` — pointers at the bottom.

## What this repo is

Donut Analytics' media mix model for the client **ABC**. It is a **Google Meridian**
Bayesian MMM (currently **v13**) that:

- pulls weekly national data from BigQuery (`donut-426.abc.mmm` view, `Model_Dates = 'In Model'`),
- fits on an **A100 GPU on Google Colab** (~8 min sampling),
- exports HTML summaries / CSVs to Google Drive (`My Drive/ABC/MMM/`),
- and (on explicit request only) rebuilds the **scenario planner** tabs in the live
  dashboard spreadsheet that Looker Studio reads.

Development happens **locally in this repo with Claude Code**. Execution has **two
interchangeable backends** sharing the same `steps/` files (details: `docs/LOCAL.md`):

- **Local (default for dev)**: `scripts/run_local.py` runs stages on the Mac — CPU
  sampling (slower fit than A100; first-run timing TBD), zero cost, zero session
  management. Outputs go to the desktop-synced Drive folder.
- **Colab (GPU escape hatch)**: `scripts/run_pipeline.sh` drives an A100 VM via the
  **`colab` CLI** (`google-colab-cli`). Use when fit speed matters or for stage 05.

There is no more copy-paste into the Colab web UI. The original notebook is preserved
at `notebooks/MMMv13_2.ipynb` (outputs stripped).

## Execution model — the one thing you must internalize

Stages are notebook cells that live in git: **they share one namespace and later stages
consume globals set by earlier ones** (`mmm`, `df_bq`, `credentials`, channel lists,
`out_dir` — set by `01` or `load`).

- On Colab, that namespace is a **live Jupyter kernel on a rented VM**; it persists
  across separate `colab exec` calls and dies on `colab stop` / `restart-kernel` /
  VM death (~24h cap).
- Locally, it's **one `run_local.py` process**; it dies when the process exits, so
  chain stages in a single invocation.

Either way, `steps/save_model.py` / `steps/load_model.py` bridge the gaps (restore a
fit in ~2 min instead of re-fitting). Saves are cross-backend — both environments
read/write the same Drive `model_saves/` folder.

## Golden rules for agents

0. **Prefer the local backend for development runs** unless Ken asks for Colab or the
   task needs the A100 (fast fit, stage 05). Rules 1–5 below are Colab-specific.
1. **Never run interactive commands**: `colab auth`, `colab drivemount`, `colab repl`,
   `colab console` need a human TTY and will hang you. If auth/mount is missing, tell Ken
   to run `colab auth -s mmm` and `colab drivemount -s mmm` in his own terminal.
2. **Always pass `--timeout`** on `colab exec` — the default is 30 s and every stage here
   exceeds it. Use the per-stage values baked into `scripts/run_pipeline.sh`.
3. **Always pass `-s <session>`** (default name: `mmm`) — never rely on implicit sessions.
4. **Stage 05 (`steps/05_scenario_planner.py`) writes to the LIVE dashboard spreadsheet**
   (`TARGET_SPREADSHEET_ID` inside it). Run it only when Ken explicitly asks. It is
   excluded from the default pipeline on purpose. It also takes ~1.5 h.
5. **A running session bills compute units until stopped** (keep-alive daemon prevents idle
   timeout). When work is done, remind Ken / run `./scripts/teardown.sh` — but only after
   `save` has run if the fit might be needed again.
6. **Never reorder `media_channels`** (or the parallel impression/spend lists) without
   reordering every prior tensor in `steps/01_fit_model.py` — priors map to channels by index.
7. **Run stage `00` (preflight) after any provision or when in doubt** — it checks GPU,
   deps, auth, Drive mount, BigQuery, and output dir, and prints exact remediations.
8. Model changes bump the version (v13 → v14): update the header comments in
   `steps/01_fit_model.py`, `docs/CHANGELOG.md`, `docs/MODEL.md`, and the `v13` filename
   prefixes/`MODEL_VERSION` markers in steps 02 and `save_model.py`.
9. Log every meaningful session's work in `docs/SESSION_LOG.md` (newest first).

## Standard workflow

```bash
# One-time machine setup (human): docs/SETUP.md (auth) + ./scripts/setup_local.sh (local env)

# --- LOCAL (default for development) ---
.venv/bin/python scripts/run_local.py               # default: 00 01 save 02 03 04
.venv/bin/python scripts/run_local.py load 03 04    # saved fit + re-run analyses
.venv/bin/python scripts/run_local.py 05            # scenario planner (explicit only)

# --- COLAB (GPU: fast fit, stage 05) ---
./scripts/provision.sh            # colab new (A100) + colab install; if run non-interactively,
                                  # prints the two human-only auth/mount commands
./scripts/run_pipeline.sh         # default: 00 01 save 02 03 04  (fit + all analyses, NOT 05)
./scripts/run_pipeline.sh 05      # scenario planner -> live dashboard sheet (explicit only)
./scripts/teardown.sh             # stop the VM (billing!)

# Iterating on one analysis while the fit sits in the kernel (Colab):
#   edit steps/03_roas_quarterly.py, then
./scripts/run_pipeline.sh 03

# Fresh Colab session, yesterday's fit:
./scripts/run_pipeline.sh 00 load 03 04
```

Useful direct commands: `colab sessions` (what's running/billing), `colab status -s mmm`,
`colab log -s mmm -n 20` (recent events, great for debugging), `colab log -s mmm -o run.ipynb`
(export session history as a notebook), `colab download -s mmm /content/x ./x`.

Two more conventions: **experiments** go on `exp/<name>` branches off `main` (merge only
winners; scorecard logged in SESSION_LOG). **Notebook escape hatch**: `scripts/
export_notebook.py` turns any branch's pipeline into a Colab-web-runnable .ipynb
(verbatim step copies + setup cell; output gitignored under `notebooks/exports/`).

## Stage map

| Stage | File | What | Typical runtime |
|-------|------|------|-----------------|
| 00 | `steps/00_check_runtime.py` | Preflight: GPU/deps/auth/Drive/BQ checks | seconds |
| 01 | `steps/01_fit_model.py` | BQ pull → priors → spec → MCMC fit | ~8 min (A100) |
| save | `steps/save_model.py` | Pickle fitted model to Drive | ~1–5 min |
| load | `steps/load_model.py` | Restore newest saved fit + re-pull data | ~2 min |
| 02 | `steps/02_diagnostics.py` | Convergence diagnostics + **HTML results summary** | ~3 min |
| 03 | `steps/03_roas_quarterly.py` | Spend-aligned ROAS by quarter + non-media attribution → CSV | minutes |
| 04 | `steps/04_decay_profiles.py` | Per-channel adstock decay profiles → CSVs + PNG | minutes |
| 05 | `steps/05_scenario_planner.py` | Scenario planner → **live dashboard sheet** | ~1.5 h (A100); local TBD |

Measured local timings (MBP, CPU, 2026-08-05 first run): 00 ≈ 5 s warm, **01 ≈ 226 s
(beats the ~8 min A100 baseline)**, save ≈ 1 s, 02 ≈ 110 s, 03 ≈ 17 s, 04 ≈ 7 s —
total ≈ 6 min. **Local is the default backend for everything except stage 05** (local
cost unmeasured; A100 recommended until measured). All outputs land in Drive at
`My Drive/ABC/MMM/` — via the mount on Colab, via the desktop-synced folder locally
(override with `MMM_OUT_DIR`). Naming conventions in `docs/MODEL.md`.

## Key facts

- BigQuery source: project `donut-426`, view `abc.mmm`, filter `Model_Dates = 'In Model'`.
  Weekly, national (single geo). KPI: `Conversions_Revenue` (dollars).
  **The view reads a Google-Sheets-backed external table** ("ABC MMM Inputs"), so every
  query needs Drive-scoped credentials — `Permission denied while getting Drive
  credentials` means the ADC scope set is wrong (fix: docs/SETUP.md § 3).
- 9 paid channels: Meta, Search, PMAX, Amex + 5 video partners (Epsilon, Google, Hulu,
  MNTN, Paramount). **Search uses clicks; all others impressions.**
- Report window in step 02: `start_date, end_date = '2025-06-29', '2026-06-21'` — must span
  52/53 week-start days; roll it forward when refreshing reports.
- Dashboard spreadsheet ID (step 05): `101EYa2FK8BJ4u6SCC4cyDvgYuWrdnP2fSaHWRk0IfVU`.
- Known limitation: **Google video low-spend ROAS extrapolation is not trustworthy**
  (Hill functional form, not a data signal). Never let the scenario planner's
  "cut Google to ~$10k/qtr at 30x" recommendation through unchallenged. See `docs/MODEL.md`.

## Where deeper docs live

- `docs/SETUP.md` — one-time machine setup: CLI install, gcloud ADC scopes, first session.
- `docs/LOCAL.md` — the local backend: setup, usage, local-vs-Colab tradeoffs, Metal note.
- `docs/WORKFLOW.md` — full (Colab) session lifecycle, recovery playbook, cost notes.
- `docs/MODEL.md` — model card: priors + rationale, spec choices, methodology of each
  analysis, known limitations, output naming.
- `docs/CHANGELOG.md` — model version history (v12 → v13 …).
- `docs/SESSION_LOG.md` — dated log of what was done/decided each working session.

## Current status (update me when it changes)

- **2026-08-05 (night)**: **First end-to-end run succeeded — local backend, 366 s
  total, fit in 226 s (faster than the A100 baseline).** All r_hat = 1.0; posteriors
  and decay profiles reproduce documented v13 behavior; `.binpb` model save works.
  Local is now the proven default for stages 00–04; stage 05 local cost still
  unmeasured. Details in `docs/SESSION_LOG.md`.

- **2026-08-05 (later)**: Added the LOCAL execution backend at Ken's request
  (`scripts/run_local.py` + `setup_local.sh` + `docs/LOCAL.md`); steps are now
  environment-aware (out_dir resolution, CPU-fit gate via `MMM_ALLOW_CPU`, per-env
  remediation messages). Local is now the default dev path; Colab remains for GPU
  speed / stage 05.
- **2026-08-05**: Repo created by migrating `MMMv13_2.ipynb` (Colab web UI) to this
  CLI-driven structure. Code is semantically 1:1 with the notebook (see MIGRATION NOTE
  headers in each migrated step, 01–05; steps 00/save/load are new). **Not yet executed end-to-end in either backend** — first
  real run pending Ken's one-time setup (docs/SETUP.md; for local also
  `./scripts/setup_local.sh`). Expect first-run wrinkles in step 02 chart saving
  (Altair `.save()`), ADC scope coverage for gspread in step 05, and unknown local
  CPU fit time; all have fallbacks/clear errors.
