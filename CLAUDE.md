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

Development happens **locally in this repo with Claude Code**; execution happens on a
remote Colab GPU driven by the **`colab` CLI** (`google-colab-cli`). There is no more
copy-paste into the Colab web UI. The original notebook this was migrated from is
preserved at `notebooks/MMMv13_2.ipynb` (outputs stripped).

## Execution model — the one thing you must internalize

A `colab` **session = a live Jupyter kernel on a rented GPU VM**. `colab exec -s <name> -f <file>`
sends a local file's code to that kernel. **Kernel state persists across exec calls** —
`steps/01_fit_model.py` leaves `mmm`, `df_bq`, `credentials`, the channel lists, and `out_dir`
as kernel globals, and steps 02–05 consume them, exactly like notebook cells sharing a runtime.
State dies on `colab stop`, `colab restart-kernel`, or VM death (~24h cap) — which is why
`steps/save_model.py` / `steps/load_model.py` exist (restore a fit in ~2 min instead of re-fitting).

## Golden rules for agents

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
# One-time machine setup (human): see docs/SETUP.md  (CLI install + gcloud ADC scopes)

./scripts/provision.sh            # colab new (A100) + colab install; if run non-interactively,
                                  # prints the two human-only auth/mount commands
./scripts/run_pipeline.sh         # default: 00 01 save 02 03 04  (fit + all analyses, NOT 05)
./scripts/run_pipeline.sh 05      # scenario planner -> live dashboard sheet (explicit only)
./scripts/teardown.sh             # stop the VM (billing!)

# Iterating on one analysis while the fit sits in the kernel:
#   edit steps/03_roas_quarterly.py, then
./scripts/run_pipeline.sh 03

# Fresh session, yesterday's fit:
./scripts/run_pipeline.sh 00 load 03 04
```

Useful direct commands: `colab sessions` (what's running/billing), `colab status -s mmm`,
`colab log -s mmm -n 20` (recent events, great for debugging), `colab log -s mmm -o run.ipynb`
(export session history as a notebook), `colab download -s mmm /content/x ./x`.

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
| 05 | `steps/05_scenario_planner.py` | Scenario planner → **live dashboard sheet** | ~1.5 h |

All outputs land in Drive at `My Drive/ABC/MMM/` (`out_dir = /content/drive/MyDrive/ABC/MMM`
on the VM). Naming conventions in `docs/MODEL.md`.

## Key facts

- BigQuery source: project `donut-426`, view `abc.mmm`, filter `Model_Dates = 'In Model'`.
  Weekly, national (single geo). KPI: `Conversions_Revenue` (dollars).
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
- `docs/WORKFLOW.md` — full session lifecycle, recovery playbook, cost notes.
- `docs/MODEL.md` — model card: priors + rationale, spec choices, methodology of each
  analysis, known limitations, output naming.
- `docs/CHANGELOG.md` — model version history (v12 → v13 …).
- `docs/SESSION_LOG.md` — dated log of what was done/decided each working session.

## Current status (update me when it changes)

- **2026-08-05**: Repo created by migrating `MMMv13_2.ipynb` (Colab web UI) to this
  CLI-driven structure. Code is semantically 1:1 with the notebook (see MIGRATION NOTE
  headers in each step). **Not yet executed end-to-end via the CLI** — first real run
  pending Ken's one-time setup (docs/SETUP.md) and session auth. Expect first-run
  wrinkles in step 02 chart saving (Altair `.save()`) and ADC scope coverage for
  gspread in step 05; both have fallbacks/clear errors.
