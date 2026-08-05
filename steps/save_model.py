# @title Utility - save the fitted model to Drive (run right after step 01)
# =============================================================================
# WHY: the fitted model lives only in kernel memory. A runtime reset / VM death
# (Colab caps sessions at ~24h) wipes it, and re-fitting costs ~8 min of A100
# time plus the pip install. Saving to Drive means steps/load_model.py can
# restore a fit in ~1-2 min instead. This did NOT exist in the notebook
# workflow - it's the fix for the "runtime reset wipes in-memory state" pain
# called out in the scenario-planner cell.
#
# Saves to: <out_dir>/model_saves/mmm_v13_<stamp>.binpb (protobuf, via Meridian's
# current serde API; falls back to deprecated .pkl pickle on older builds).
# The file contains the full model incl. posterior draws (can be several
# hundred MB - fine on Drive, do NOT commit to git).
#
# REQUIRES kernel state from step 01 (mmm, out_dir).
# Run via:  colab exec -s <session> -f steps/save_model.py --timeout 3600
# =============================================================================
import datetime
import os

_missing = [n for n in ('mmm', 'out_dir') if n not in globals()]
if _missing:
    raise RuntimeError(f"Missing kernel globals: {_missing}. Run steps/01_fit_model.py first.")

MODEL_VERSION = 'v13'
_save_dir = os.path.join(out_dir, 'model_saves')
os.makedirs(_save_dir, exist_ok=True)
_stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

# Prefer Meridian's current serde API (protobuf .binpb - cross-version safe); fall back
# to the deprecated pickle API on older Meridian builds. load_model.py handles both
# formats. Ref: developers.google.com/meridian/docs/user-guide/saving-model-object
try:
    from meridian.schema.serde import meridian_serde
    _save_path = os.path.join(_save_dir, f"mmm_{MODEL_VERSION}_{_stamp}.binpb")
    meridian_serde.save_meridian(mmm, _save_path)
except ImportError:
    from meridian.model import model as mmm_module
    _save_path = os.path.join(_save_dir, f"mmm_{MODEL_VERSION}_{_stamp}.pkl")
    mmm_module.save_mmm(mmm, _save_path)  # deprecated upstream; pickle ties save to version
_size_mb = os.path.getsize(_save_path) / 1e6
print(f"Saved fitted model to {_save_path} ({_size_mb:,.0f} MB)")
print("Restore later (fresh session) with: colab exec -s <session> -f steps/load_model.py --timeout 3600")
