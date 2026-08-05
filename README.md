# ABC Media Mix Model

Google **Meridian** Bayesian MMM for ABC (Donut Analytics). Developed locally
(Claude Code / any editor); executed either **locally on the Mac (CPU)** or on a
**Google Colab A100** via the
[Colab CLI](https://github.com/googlecolab/google-colab-cli) — no Colab web UI,
no copy-paste. Model version: **v13**.

```
BigQuery (donut-426.abc.mmm)
        │  weekly national data, Model_Dates = 'In Model'
        ▼
steps/01_fit_model.py ──► Meridian MCMC fit on Colab A100 (~8 min)
        │                                (kernel keeps `mmm` in memory)
        ├─► steps/02_diagnostics.py ───► HTML results summary + convergence charts ─► Google Drive
        ├─► steps/03_roas_quarterly.py ► spend-aligned ROAS by quarter CSV ─────────► Google Drive
        ├─► steps/04_decay_profiles.py ► adstock decay CSVs + plot ─────────────────► Google Drive
        └─► steps/05_scenario_planner.py ► scenario planner tabs ─► LIVE dashboard Sheet ─► Looker Studio
```

## Quickstart

One-time machine setup (Google auth; local venv; optionally the Colab CLI):
**[docs/SETUP.md](docs/SETUP.md)** and **[docs/LOCAL.md](docs/LOCAL.md)**.

**Local (default for development — free, no session management, CPU fit):**

```bash
./scripts/setup_local.sh                     # once: .venv + Meridian CPU stack
.venv/bin/python scripts/run_local.py        # preflight, fit, save, diagnostics, ROAS, decay
.venv/bin/python scripts/run_local.py 05     # scenario planner (explicit only — live dashboard)
```

**Colab (A100 — fast fit; preferred for the ~1.5 h scenario planner):**

```bash
./scripts/provision.sh          # rent an A100 + install deps (+ interactive auth/mount)
./scripts/run_pipeline.sh       # preflight, fit, save model, diagnostics, ROAS, decay
./scripts/run_pipeline.sh 05    # scenario planner (explicit only — writes the live dashboard)
./scripts/teardown.sh           # stop the VM — it bills until you do
```

Either way, outputs land in Google Drive at `My Drive/ABC/MMM/` (HTML summaries, CSVs,
diagnostics, model saves) — same place the notebook always wrote them. Model saves are
cross-backend: fit on the A100, analyze locally, or vice versa.

## Repo map

| Path | What |
|------|------|
| `steps/` | The pipeline, one file per former notebook cell; environment-aware (Colab or local). Stages share one namespace — later stages consume globals from `01`/`load`. |
| `scripts/` | Runners: `run_local.py` + `setup_local.sh` (local backend); `provision.sh` / `run_pipeline.sh` / `teardown.sh` (Colab backend). |
| `requirements-colab.txt` | Installed **on the Colab VM** each session (`google-meridian[colab,scenarioplanner,and-cuda]`). |
| `requirements-local.txt` | Installed into `.venv` by `setup_local.sh` (Meridian without CUDA; TF on CPU). |
| `notebooks/MMMv13_2.ipynb` | The original Colab notebook this was migrated from (outputs stripped, provenance only — the `steps/` files are the source of truth now). |
| `CLAUDE.md` | Agent onboarding — read first in every Claude Code session. |
| `docs/` | Setup, workflow, model card, changelog, session log. |

## Documentation

- [docs/SETUP.md](docs/SETUP.md) — one-time setup (CLI, gcloud ADC scopes, Colab Pro)
- [docs/LOCAL.md](docs/LOCAL.md) — local execution: setup, usage, local-vs-Colab tradeoffs
- [docs/WORKFLOW.md](docs/WORKFLOW.md) — day-to-day Colab operation + recovery playbook
- [docs/MODEL.md](docs/MODEL.md) — model card: data, priors, spec, methodology, limitations
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — model version history
- [docs/SESSION_LOG.md](docs/SESSION_LOG.md) — dated working-session log
