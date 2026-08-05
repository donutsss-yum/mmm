# @title Step 00 - Runtime preflight checks (fast, run first on every new session)
# =============================================================================
# WHAT THIS IS
# Validates the Colab VM is ready for the MMM pipeline BEFORE burning GPU time:
#   1. Running on a Colab runtime
#   2. GPU present (A100 expected; sampling on CPU takes hours, not minutes)
#   3. Meridian + friends importable (else: colab install -s <session> -r requirements-colab.txt)
#   4. Google credentials present on the VM (else: colab auth -s <session>  [interactive - human required])
#   5. Google Drive mounted at /content/drive (else: colab drivemount -s <session>  [interactive - human required])
#   6. BigQuery reachable (tiny SELECT 1 against project donut-426)
#   7. Output directory on Drive exists and is writable
#
# Prints one PASS/FAIL line per check with the exact remediation command.
# Raises RuntimeError at the end if any HARD check failed, so `colab exec`
# surfaces a non-zero-looking failure instead of a silent partial pass.
#
# Run via:  colab exec -s <session> -f steps/00_check_runtime.py --timeout 300
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


# 1) On a Colab runtime at all?
try:
    import google.colab  # noqa: F401
    _on_colab = True
except ImportError:
    _on_colab = False
_check("Running on a Colab runtime", _on_colab,
       "This script is meant to run on the Colab VM via `colab exec`, not locally.")

# 2) GPU
try:
    import tensorflow as tf
    gpus = tf.config.list_physical_devices('GPU')
    gpu_ok = len(gpus) > 0
    detail = ", ".join(d.name for d in gpus) if gpus else "none"
    print(f"       GPU devices: {detail} | TF {tf.__version__}")
except Exception as e:  # TF missing entirely counts as check 3's problem too
    gpu_ok = False
    print(f"       (TensorFlow import failed: {type(e).__name__}: {e})")
_check("GPU available", gpu_ok,
       "Provision with a GPU: colab stop -s <session>; colab new -s <session> --gpu A100. "
       "Fitting on CPU is impractically slow (hours vs ~8 min).")

# 3) Meridian + the rest of the stack
_import_errors = []
for _mod in ("meridian", "pandas_gbq", "arviz", "tensorflow_probability", "gspread"):
    try:
        __import__(_mod)
    except Exception as e:
        _import_errors.append(f"{_mod} ({type(e).__name__})")
_check("Python deps importable (meridian, pandas_gbq, arviz, tfp, gspread)",
       not _import_errors,
       f"Missing: {', '.join(_import_errors)}. Fix from your LOCAL terminal: "
       f"colab install -s <session> -r requirements-colab.txt")

# 4) Google credentials on the VM (needed for BigQuery in step 01, Sheets in step 05)
_creds_ok = False
try:
    import google.auth
    _creds, _proj = google.auth.default()
    _creds_ok = True
    print(f"       ADC project: {_proj}")
except Exception as e:
    print(f"       ({type(e).__name__}: {e})")
_check("Google credentials present on VM", _creds_ok,
       "From your LOCAL terminal run: colab auth -s <session>   "
       "(INTERACTIVE - a human must complete the browser flow; agents must not run this)")

# 5) Drive mounted (all pipeline outputs land in /content/drive/MyDrive/ABC/MMM)
_drive_ok = os.path.isdir('/content/drive/MyDrive')
_check("Google Drive mounted at /content/drive", _drive_ok,
       "From your LOCAL terminal run: colab drivemount -s <session>   "
       "(INTERACTIVE - a human must complete the flow; agents must not run this)")

# 6) BigQuery reachable (source data lives in donut-426.abc.mmm)
_bq_ok = False
if _creds_ok:
    try:
        import pandas_gbq
        pandas_gbq.read_gbq("SELECT 1 AS ok", project_id="donut-426", progress_bar_type=None)
        _bq_ok = True
    except Exception as e:
        print(f"       ({type(e).__name__}: {e})")
_check("BigQuery reachable (project donut-426)", _bq_ok,
       "Usually a credentials/scope problem - re-run `colab auth -s <session>`.")

# 7) Output dir writable
OUT_DIR = '/content/drive/MyDrive/ABC/MMM'
_out_ok = False
if _drive_ok:
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        _probe = os.path.join(OUT_DIR, '.write_probe')
        with open(_probe, 'w') as f:
            f.write('ok')
        os.remove(_probe)
        _out_ok = True
    except Exception as e:
        print(f"       ({type(e).__name__}: {e})")
_check(f"Output dir writable: {OUT_DIR}", _out_ok,
       "Check the Drive mount and that the ABC/MMM folder exists in My Drive.")

print()
if _failures:
    raise RuntimeError(
        f"Preflight FAILED ({len(_failures)} hard failure(s)): {', '.join(_failures)}. "
        f"Fix the items above, then re-run this step before starting the pipeline."
    )
print("ALL PREFLIGHT CHECKS PASSED - runtime is ready for steps 01-05.")
