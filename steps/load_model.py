# @title Utility - restore a saved fit instead of re-sampling (~2 min vs ~8 min + install)
# =============================================================================
# WHAT THIS IS
# Rebuilds ALL the kernel state that steps 02-05 need, WITHOUT re-fitting:
#   1. Credentials (ADC - requires `colab auth` done for this session)
#   2. The BigQuery data pull + channel/variable definitions (fast, no sampling)
#      - needed because steps 03/04 read df_bq and the channel lists directly
#   3. The fitted `mmm` object, loaded from the newest save in
#      /content/drive/MyDrive/ABC/MMM/model_saves/ (or set LOAD_PATH explicitly)
#
# The data-pull + definitions section MUST stay in sync with
# steps/01_fit_model.py. If you change channels/columns there, change them here.
# (They are duplicated because each step file must be self-contained for
# `colab exec`; a shared module would need a manual upload step. Future
# improvement if drift becomes a problem.)
#
# CAUTION: a loaded model was fit on the data AS OF its save date. If the
# BigQuery view has new weeks since then, analyses that mix `mmm` (old fit)
# with `df_bq` (fresh pull) can be inconsistent - re-fit via step 01 when the
# data has been updated.
#
# Run via:  colab exec -s <session> -f steps/load_model.py --timeout 3600
# =============================================================================

LOAD_PATH = None  # set to an explicit .pkl path to load a specific save; None = newest

import glob
import os

# --- 1) credentials (same as step 01) ----------------------------------------
try:
    import google.auth
    credentials, _adc_project = google.auth.default(scopes=[
        'https://www.googleapis.com/auth/bigquery',
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets',
    ])
except Exception as _e:
    raise RuntimeError(
        "No Google credentials on the VM. From your LOCAL terminal run "
        "`colab auth -s <session>` (interactive - human required), then re-run this step. "
        f"Underlying error: {type(_e).__name__}: {_e}"
    )

import pandas as pd
import pandas_gbq

out_dir = '/content/drive/MyDrive/ABC/MMM'
if not os.path.isdir('/content/drive/MyDrive'):
    raise RuntimeError(
        "Google Drive is not mounted, so there is nothing to load from. "
        "From your LOCAL terminal run `colab drivemount -s <session>` (interactive)."
    )

# --- 2) data pull + definitions (MUST mirror steps/01_fit_model.py) ----------
project_id = 'donut-426'
view_sql = """SELECT * FROM abc.mmm WHERE Model_Dates = 'In Model'"""

df_bq = pandas_gbq.read_gbq(view_sql, project_id=project_id)
if 'time' not in df_bq.columns:
    raise ValueError("Expected a 'time' column in BigQuery data.")
df_bq['time'] = pd.to_datetime(df_bq['time'])

media_channels = ['Meta', 'Search', 'PMAX', 'Amex',
                  'Video_Epsilon', 'Video_Google', 'Video_Hulu',
                  'Video_MNTN', 'Video_Paramount']

media_impression_cols = ['Meta_impression', 'Search_click', 'PMAX_impression', 'Amex_impression',
                         'Video_Epsilon_impression', 'Video_Google_impression', 'Video_Hulu_impression',
                         'Video_MNTN_impression', 'Video_Paramount_impression']

media_spend_cols = [f"{ch}_spend" for ch in media_channels]

non_media_cols = ['Vault_Drops','Email_sends','Redemptions_Other','StoreCount']

control_cols = ['Category_Interest', 'Hurricanes', 'LightningSales', 'Redemptions_Birthday_Signup','Celebs']

print("Data pulled. Shape:", df_bq.shape)

# --- 3) load the fitted model ------------------------------------------------
from meridian.model import model as mmm_module

if LOAD_PATH is None:
    _saves = sorted(glob.glob(os.path.join(out_dir, 'model_saves', 'mmm_*.pkl')))
    if not _saves:
        raise RuntimeError(
            f"No saved models found in {out_dir}/model_saves/. "
            f"Run steps/01_fit_model.py then steps/save_model.py first."
        )
    LOAD_PATH = _saves[-1]  # timestamped names sort chronologically

print(f"Loading model from {LOAD_PATH} ...")
mmm = mmm_module.load_mmm(LOAD_PATH)
print("Model restored. Kernel globals now set: mmm, df_bq, credentials, media_channels, "
      "media_impression_cols, media_spend_cols, non_media_cols, control_cols, out_dir.")
print("Steps 02-05 can now run without a re-fit.")
