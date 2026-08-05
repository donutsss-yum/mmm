# Running locally (no Colab)

The pipeline has **two interchangeable execution backends** sharing the exact same
`steps/` files:

| | Local (MacBook Pro) | Colab (via CLI) |
|---|---|---|
| Runner | `scripts/run_local.py` (one Python process = the "kernel") | `scripts/run_pipeline.sh` (`colab exec` into a VM kernel) |
| Hardware | CPU (TFP/MCMC can't reliably use Apple's Metal GPU) | A100 GPU |
| Fit time (step 01) | **Unknown until first run** — expect well over the A100's ~8 min (plausibly 30 min–a few hours) | ~8 min |
| Scenario planner (05) | Likely very slow (~1.5 h on A100) — prefer Colab or run overnight | ~1.5 h |
| Cost | Free | Compute units while VM is up |
| Session management | None — no billing, no auth-per-session, no teardown | provision/auth/mount/stop dance |
| Outputs | Desktop-synced Drive folder (`~/Library/CloudStorage/GoogleDrive-ken@donutanalytics.com/My Drive/ABC/MMM`) — syncs to the same cloud folder | Drive mount (`/content/drive/MyDrive/ABC/MMM`) |

**Practical guidance:** develop and iterate locally (it's free and frictionless); jump
to Colab when you need the fit fast or for the scenario planner. Model saves are
interchangeable — a fit saved on Colab can be `load`-ed locally and vice versa, since
both write `model_saves/` to the same Drive folder. RAM is not a constraint either way:
this is a small national-level model (~174 weeks); it's sampler *speed* that differs.

## One-time setup

```bash
./scripts/setup_local.sh     # .venv (Python 3.12 via uv) + Meridian CPU stack
```

Plus Google auth once per machine — SETUP.md § 3, which has TWO required sub-steps:
trust the gcloud OAuth client in the Workspace admin console (3a), then mint ADC with
the full scope list (3b). The Drive scope in that list is load-bearing for every run:
the `abc.mmm` BigQuery view reads a Sheets-backed table, and querying it without
Drive-scoped credentials fails with `Permission denied while getting Drive
credentials`.

## Running

```bash
.venv/bin/python scripts/run_local.py 00            # preflight
.venv/bin/python scripts/run_local.py               # 00 01 save 02 03 04
.venv/bin/python scripts/run_local.py load 03 04    # yesterday's fit, fresh analyses
.venv/bin/python scripts/run_local.py 05            # scenario planner — EXPLICIT ONLY
                                                    #   (writes the LIVE dashboard sheet)
```

Semantics match Colab exactly: stages share one namespace, `01` (or `load`) sets the
globals that `02`–`05` consume. The one difference: **state dies when the process
exits** (there's no persistent kernel), so chain stages in a single invocation or
bridge invocations with `save`/`load`. The default chain already saves right after
the fit.

Flags: `--out-dir PATH` overrides the output folder (also honored as `MMM_OUT_DIR`
env var); `--require-gpu` makes the fit fail rather than run on CPU (the default
locally is CPU-allowed via `MMM_ALLOW_CPU=1`).

## First local run: what to watch

1. **Time the fit.** Note wall-clock for stage 01 in `docs/SESSION_LOG.md` — it decides
   how much we still care about Colab for everyday runs.
2. TF on CPU may print AVX/oneDNN info lines — noise, ignore.
3. `pandas_gbq` may warn about no quota project with user ADC — harmless (we pass
   `project_id` explicitly).
4. If step 01 dies with an auth error — especially `Permission denied while getting
   Drive credentials` — redo SETUP.md § 3 in full: the Workspace allow-list (3a) must
   be in place, and ADC must be minted with the complete scope list (3b), Drive scope
   included. A plain `gcloud auth application-default login` is never enough.

## Apple GPU (tensorflow-metal) — experimental, off by default

`uv pip install --python .venv/bin/python tensorflow-metal` enables Apple-GPU
acceleration, **but** TFP's MCMC has a history of missing/incorrect ops on Metal.
If you try it: run a clean CPU fit first, then a Metal fit, and compare `az.summary`
posteriors — keep Metal only if they match and it's actually faster. Remove with
`uv pip uninstall --python .venv/bin/python tensorflow-metal`.
