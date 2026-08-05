# ABC Media Mix Model

Google **Meridian** Bayesian MMM for ABC (Donut Analytics). Developed locally
(Claude Code / any editor), executed on a **Google Colab A100** via the
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

One-time machine setup (install CLI + Google auth): **[docs/SETUP.md](docs/SETUP.md)**.

```bash
./scripts/provision.sh          # rent an A100 + install deps (+ interactive auth/mount)
./scripts/run_pipeline.sh       # preflight, fit, save model, diagnostics, ROAS, decay
./scripts/run_pipeline.sh 05    # scenario planner (explicit only — writes the live dashboard)
./scripts/teardown.sh           # stop the VM — it bills until you do
```

Outputs land in Google Drive at `My Drive/ABC/MMM/` (HTML summaries, CSVs,
diagnostics, model saves) — same place the notebook always wrote them.

## Repo map

| Path | What |
|------|------|
| `steps/` | The pipeline, one file per former notebook cell; run on the Colab kernel via `colab exec`. Kernel state persists between steps. |
| `scripts/` | Local shell runners: provision / run stages with correct timeouts / teardown. |
| `requirements-colab.txt` | Installed **on the VM** each session (`google-meridian[colab,scenarioplanner,and-cuda]`). |
| `notebooks/MMMv13_2.ipynb` | The original Colab notebook this was migrated from (outputs stripped, provenance only — the `steps/` files are the source of truth now). |
| `CLAUDE.md` | Agent onboarding — read first in every Claude Code session. |
| `docs/` | Setup, workflow, model card, changelog, session log. |

## Documentation

- [docs/SETUP.md](docs/SETUP.md) — one-time setup (CLI, gcloud ADC scopes, Colab Pro)
- [docs/WORKFLOW.md](docs/WORKFLOW.md) — day-to-day operation + recovery playbook
- [docs/MODEL.md](docs/MODEL.md) — model card: data, priors, spec, methodology, limitations
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — model version history
- [docs/SESSION_LOG.md](docs/SESSION_LOG.md) — dated working-session log
