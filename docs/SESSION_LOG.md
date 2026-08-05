# Session log

Newest first. One entry per meaningful working session: what was done, what was
decided, what's pending. Keep `CLAUDE.md`'s "Current status" in sync.

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
  cells into the Colab web UI). The 5 notebook cells became `steps/00–05` plus
  `save_model.py` / `load_model.py`; every step carries a MIGRATION NOTE header
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
