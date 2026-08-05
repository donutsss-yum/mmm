# @title Step 00 - Runtime preflight checks (fast, run first in every environment)
# =============================================================================
# WHAT THIS IS
# Validates the runtime is ready for the MMM pipeline BEFORE burning compute
# time. Works in BOTH execution environments (see docs/LOCAL.md):
#   - Colab VM   (driven via `colab exec` from the Colab CLI)
#   - Local Mac  (driven via scripts/run_local.py; CPU sampling, synced Drive folder)
#
# Checks:
#   1. Which environment we're in (informational)
#   2. GPU present - HARD requirement on Colab (that's what you're paying for),
#      warning locally (CPU sampling is expected there, just slower)
#   3. Meridian + friends importable
#   4. Google credentials present (ADC)
#   5. Output folder reachable (Drive mount on Colab / synced Drive folder locally)
#   6. BigQuery reachable (tiny SELECT 1 against project donut-426)
#   7. Output directory writable
#
# Prints one PASS/FAIL/WARN line per check with the exact remediation command.
# Raises RuntimeError at the end if any HARD check failed.
#
# Run on Colab:  colab exec -s <session> -f steps/00_check_runtime.py --timeout 300
# Run locally:   .venv/bin/python scripts/run_local.py 00
# =============================================================================
import os

_failures = []
_warnings = []


def _check(name, ok, remediation="", hard=True):
    status = "PASS" if ok else ("FAIL" if hard else "WARN")
    print(f"[{status}] {name}")
    if not ok and remediation:
        print(f"       -> {remediation}")
    if not ok:
        (_failures if hard else _warnings).append(name)


# 1) Environment
IS_COLAB = os.path.isdir('/content')
print(f"[INFO] Environment: {'Colab VM' if IS_COLAB else 'local machine'}")

# 2) GPU - hard on Colab, soft locally (Apple silicon has no CUDA; CPU fit is the plan)
try:
    import tensorflow as tf
    gpus = tf.config.list_physical_devices('GPU')
    gpu_ok = len(gpus) > 0
    detail = ", ".join(d.name for d in gpus) if gpus else "none"
    print(f"       GPU devices: {detail} | TF {tf.__version__}")
except Exception as e:  # TF missing entirely counts as check 3's problem too
    gpu_ok = False
    print(f"       (TensorFlow import failed: {type(e).__name__}: {e})")
if IS_COLAB:
    _check("GPU available", gpu_ok,
           "Provision with a GPU: colab stop -s <session>; colab new -s <session> --gpu A100. "
           "Fitting on Colab CPU wastes the session (hours vs ~8 min).")
else:
    _check("GPU available (CPU sampling expected locally - fit will be much slower than A100)",
           gpu_ok, "This is fine: scripts/run_local.py enables CPU fits. Use the Colab path "
           "for GPU speed (docs/WORKFLOW.md).", hard=False)

# 3) Meridian + the rest of the stack
_import_errors = []
for _mod in ("meridian", "pandas_gbq", "arviz", "tensorflow_probability", "gspread"):
    try:
        __import__(_mod)
    except Exception as e:
        _import_errors.append(f"{_mod} ({type(e).__name__})")
_fix_deps = ("colab install -s <session> -r requirements-colab.txt  (from your LOCAL terminal)"
             if IS_COLAB else
             "./scripts/setup_local.sh   (creates .venv and installs requirements-local.txt)")
_check("Python deps importable (meridian, pandas_gbq, arviz, tfp, gspread)",
       not _import_errors,
       f"Missing: {', '.join(_import_errors)}. Fix: {_fix_deps}")

# 4) Google credentials (needed for BigQuery in step 01, Sheets in step 05)
_creds_ok = False
try:
    import google.auth
    _creds, _proj = google.auth.default()
    _creds_ok = True
    print(f"       ADC project: {_proj}")
except Exception as e:
    print(f"       ({type(e).__name__}: {e})")
_fix_auth = ("colab auth -s <session>   (INTERACTIVE - human required; agents must not run this)"
             if IS_COLAB else
             "the `gcloud auth application-default login --scopes=...` command in docs/SETUP.md")
_check("Google credentials present (ADC)", _creds_ok, f"Fix: {_fix_auth}")

# 5) Output folder reachable + 7) writable
_LOCAL_DRIVE_DIR = os.path.expanduser(
    '~/Library/CloudStorage/GoogleDrive-ken@donutanalytics.com/My Drive/ABC/MMM')
OUT_DIR = os.environ.get('MMM_OUT_DIR') or (
    '/content/drive/MyDrive/ABC/MMM' if IS_COLAB else _LOCAL_DRIVE_DIR)

if IS_COLAB:
    _reach_ok = os.path.isdir('/content/drive/MyDrive')
    _check("Google Drive mounted at /content/drive", _reach_ok,
           "From your LOCAL terminal run: colab drivemount -s <session>   "
           "(INTERACTIVE - human required; agents must not run this)")
else:
    _reach_ok = os.path.isdir(OUT_DIR)
    _check(f"Synced Drive folder present: {OUT_DIR}", _reach_ok,
           "Check Google Drive desktop sync is running and the ABC/MMM folder exists, "
           "or set MMM_OUT_DIR to an alternative output folder.")

# 6) BigQuery reachable AND the actual source view queryable. The probe hits abc.mmm
#    itself (not SELECT 1) because the view reads a Google-Sheets-backed external
#    table: querying it requires DRIVE-scoped credentials, which a plain reachability
#    check would not exercise (learned the hard way on first local run, 2026-08-05).
_bq_ok = False
_bq_err = ""
if _creds_ok:
    try:
        import pandas_gbq
        pandas_gbq.read_gbq(
            "SELECT time FROM abc.mmm WHERE Model_Dates = 'In Model' LIMIT 1",
            project_id="donut-426", progress_bar_type=None)
        _bq_ok = True
    except Exception as e:
        _bq_err = str(e)
        print(f"       ({type(e).__name__}: {e})")
if not _bq_ok and 'Drive credentials' in _bq_err:
    _bq_fix = ("Your credentials lack the Drive scope that BigQuery needs to read the "
               "Sheets-backed table behind abc.mmm. See docs/SETUP.md section 3: trust the "
               "gcloud OAuth client in the Workspace admin console, then re-run the ADC "
               "login WITH the drive scope." if not IS_COLAB else
               "Re-run `colab auth -s <session>` - the VM's credentials lack Drive access.")
else:
    _bq_fix = f"Usually a credentials/scope problem - fix: {_fix_auth}"
_check("BigQuery source view queryable (donut-426, abc.mmm)", _bq_ok, _bq_fix)

# 7) Output dir writable
_out_ok = False
if _reach_ok:
    try:
        _probe = os.path.join(OUT_DIR, '.write_probe')
        with open(_probe, 'w') as f:
            f.write('ok')
        os.remove(_probe)
        _out_ok = True
    except Exception as e:
        print(f"       ({type(e).__name__}: {e})")
_check(f"Output dir writable: {OUT_DIR}", _out_ok,
       "Check the Drive mount / desktop sync and folder permissions.")

print()
if _failures:
    raise RuntimeError(
        f"Preflight FAILED ({len(_failures)} hard failure(s)): {', '.join(_failures)}. "
        f"Fix the items above, then re-run this step before starting the pipeline."
    )
if _warnings:
    print(f"Preflight passed with {len(_warnings)} warning(s): {', '.join(_warnings)}")
print("PREFLIGHT OK - runtime is ready for steps 01-05.")
