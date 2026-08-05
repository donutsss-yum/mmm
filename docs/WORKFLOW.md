# Day-to-day workflow (Colab backend)

One-time machine setup is in [SETUP.md](SETUP.md). This page is the operating manual for
a **Colab** working session; for the local backend (no VM, no billing, CPU fit) see
[LOCAL.md](LOCAL.md). The stage table (files, runtimes) lives in `CLAUDE.md`; per-stage
exec timeouts live in `scripts/run_pipeline.sh`.

## Mental model

- **Session = named Jupyter kernel on a rented VM.** We use the session name **`mmm`**
  (override with `MMM_SESSION=...`).
- `colab exec -s mmm -f steps/XX.py --timeout N` reads the local file and runs it **in
  that kernel**. Variables persist between calls — the steps are notebook cells that
  happen to live in git.
- The VM **bills compute units until `colab stop`**; the CLI's keep-alive daemon
  deliberately prevents idle shutdown. There is also a hard ~24 h session cap.
- Editing a step file locally and re-exec'ing it is the whole dev loop. No uploads —
  the CLI ships the file's contents on every exec.

## The normal day

```bash
./scripts/provision.sh                 # new VM: A100 + deps (+ interactive auth/mount)
./scripts/run_pipeline.sh              # 00 01 save 02 03 04
# ... inspect outputs in Drive: My Drive/ABC/MMM/ ...
./scripts/teardown.sh                  # STOP THE METER
```

Re-running a single analysis after editing it (fit already in the kernel):

```bash
./scripts/run_pipeline.sh 03
```

Fresh VM but yesterday's fit (skips the ~8 min sample + gets consistent results):

```bash
./scripts/provision.sh                 # + the two interactive auth steps
./scripts/run_pipeline.sh 00 load 02 03 04
```

Scenario planner — **deliberate, explicit, ~1.5 h, writes the live dashboard sheet**:

```bash
./scripts/run_pipeline.sh 05
```

## Inspecting a session

```bash
colab sessions                  # what's up (and billing) right now
colab status -s mmm             # hardware, IDLE/BUSY, last execution
colab log -s mmm -n 20          # recent structured events (best first stop on failures)
colab log -s mmm -o run.ipynb   # export the whole session history as a notebook
colab url -s mmm --open         # attach the Colab web UI to this same kernel (handy
                                #   for eyeballing; do NOT run cells that clobber state)
colab download -s mmm /content/some_file ./some_file
```

## Recovery playbook

| Symptom | Diagnosis | Fix |
|---|---|---|
| Step fails: `Missing kernel globals: ['mmm', ...]` | Kernel restarted or fit never ran | `./scripts/run_pipeline.sh load` (restores newest save) or re-run `01` |
| `No Google credentials available` | `colab auth` not done for this VM | Human runs `colab auth -s mmm` |
| Outputs error: `/content/drive/... not found` | Drive not mounted on this VM | Human runs `colab drivemount -s mmm` |
| `ImportError: meridian` | New/reset VM without deps | `colab install -s mmm -r requirements-colab.txt` |
| `Session not found` / 404 / 401 on exec | Backend reclaimed the VM (24 h cap, etc.) | `colab sessions`, then `./scripts/provision.sh` and `load` |
| exec hangs then times out; kernel BUSY | Long computation still running server-side | Check `colab status -s mmm`; wait or `colab restart-kernel -s mmm` (kills kernel state!) |
| CLI 403 `colab.pa.googleapis.com` | Local ADC missing a scope | Re-run the gcloud command in SETUP.md; verify `colab whoami` |
| `colab new --gpu A100` returns 400 | No A100 quota/entitlement right now | Try again later, or `MMM_GPU=T4 ./scripts/provision.sh` (slower fit) |

Golden recovery rule: **the newest model save + `load` beats re-fitting** whenever the
underlying data hasn't changed. If BigQuery has new weeks, re-fit (`01`) instead —
a stale `mmm` against fresh `df_bq` mixes vintages (load_model prints this caution too).

## Cost discipline

- A100 sessions consume compute units the entire time the VM exists — including while
  you're reading results. Park work: `save` → `teardown`, resume later with `load`.
- The fit itself is ~8 min; the expensive stages are scenario planner (~1.5 h) and
  forgetting teardown (∞).
- `colab sessions` at the end of the day should list nothing.

## Escape hatch: export a Colab-web notebook

Any state of the repo (any branch, any experiment) can be exported as a classic
notebook and run "the old fashioned way" in the Colab web UI:

```bash
.venv/bin/python scripts/export_notebook.py                # default: 00 01 save 02 03 04
.venv/bin/python scripts/export_notebook.py --stages 05    # subset / scenario planner
```

Output lands in `notebooks/exports/` (gitignored) with the branch + commit stamped in
the first cell. Upload via File → Upload notebook at colab.research.google.com, pick
an A100 runtime, run top to bottom — the first cell handles pip/auth/Drive, the rest
are verbatim copies of `steps/`. Edits made inside the exported notebook do NOT flow
back to git; re-export after changing the repo.

## Experiment branches

Model experiments live on `exp/<name>` branches cut from `main`
(e.g. `exp/v14-revenue-split`), never on `main` directly. Merge only winners —
the scorecard (holdout comparison, convergence, attribution sanity) goes in
`SESSION_LOG.md` either way. Every experiment can be notebook-exported for a
Colab-web run exactly like `main`.

## Editing / development conventions

- The step files ARE the model definition — the notebook in `notebooks/` is a frozen
  historical copy. Never edit the notebook expecting effects.
- Priors and channel lists change **only** in `steps/01_fit_model.py`, mirrored manually
  in `steps/load_model.py` (data-pull section) — keep them in sync.
- Any model-behavior change = version bump (see checklist in `CLAUDE.md`) + entries in
  `CHANGELOG.md` and `SESSION_LOG.md`.
- Report window (`start_date`/`end_date` in step 02) rolls forward as new quarters close.
