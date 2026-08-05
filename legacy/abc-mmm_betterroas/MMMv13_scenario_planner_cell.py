# @title Scenario planner builder (takes 1.5rhrs) - writes to existing dashboard sheet on A100

# ---------------------------------------------------------------------------
# Defensive install + prereqs check: in case the Colab runtime was reset since cell 0 (MMMv13) ran.
# A reset wipes installed packages AND your fitted `mmm` model. The pip line below is a no-op if
# Meridian is already installed; the assert tells you clearly if you need to re-run cell 0 first.
# ---------------------------------------------------------------------------
!pip -q install --upgrade google-meridian[colab,scenarioplanner,and-cuda]

_missing = [n for n in ('mmm', 'credentials') if n not in globals()]
if _missing:
    raise RuntimeError(
        f"Missing required variable(s) from cell 0: {_missing}. Re-run cell 0 (MMMv13 model spec) "
        f"first - it fits the model and leaves it in scope as `mmm`. Runtime resets wipe in-memory "
        f"state, so the full ~45 min sampling step has to be redone."
    )

from IPython.display import HTML
import inspect

from meridian.schema.processors import (
    model_fit_processor,
    marketing_processor,
    budget_optimization_processor,
)
from meridian.schema.utils import date_range_bucketing
from scenarioplanner.converters import sheets
from scenarioplanner.converters.dataframe import dataframe_model_converter
from scenarioplanner import mmm_ui_proto_generator as mmm_ui_gen
from scenarioplanner.linkingapi import url_generator

print('Scenario Planner imports ready.')

# ---------------------------------------------------------------------------
# v13 UPDATE: write to the EXISTING dashboard spreadsheet instead of creating a new sheet each run. Target
# the sheet your dashboard already points at so refresh pulls the latest data automatically. The runtime
# tries Meridian's native helper first (if any version of upload_to_gsheet ever supports targeting by ID),
# then falls back to direct gspread writes to the same sheet ID.
# ---------------------------------------------------------------------------
TARGET_SPREADSHEET_ID = '101EYa2FK8BJ4u6SCC4cyDvgYuWrdnP2fSaHWRk0IfVU'

optimization_name = 'ABC FY26'  # @param {"type":"string"}
include_non_paid_channels = True  # @param {"type":"boolean"}

yearly = True       # @param {"type":"boolean"}
quarterly = True    # @param {"type":"boolean"}
monthly = False     # @param {"type":"boolean"}

min_spend_shift_ratio = 0.40  # @param {"type":"raw"}
max_spend_shift_ratio = 0.40  # @param {"type":"raw"}
use_optimal_frequency = False  # @param {"type":"boolean"}

max_frequency = 10.0          # @param {"type":"raw"}

time_breakdown_generators = []
if yearly:    time_breakdown_generators.append(date_range_bucketing.YearlyDateRangeGenerator)
if quarterly: time_breakdown_generators.append(date_range_bucketing.QuarterlyDateRangeGenerator)
if monthly:   time_breakdown_generators.append(date_range_bucketing.MonthlyDateRangeGenerator)

channel_constraints = [
    budget_optimization_processor.ChannelConstraintRel(
        channel_name=ch,
        spend_constraint_lower=min_spend_shift_ratio,
        spend_constraint_upper=max_spend_shift_ratio,
    )
    for ch in mmm.input_data.get_all_paid_channels()
]

budget_opt_spec = budget_optimization_processor.BudgetOptimizationSpec(
    start_date=None,
    end_date=None,
    optimization_name=optimization_name,
    grid_name='-'.join(optimization_name.lower().split(' ')),
    constraints=channel_constraints,
    use_optimal_frequency=use_optimal_frequency,
    max_frequency=max_frequency,
)

print('Running scenario inference - ~45 min on h1100.')
mmm_proto = mmm_ui_gen.create_mmm_ui_data_proto(
    mmm=mmm,
    specs=[
        model_fit_processor.ModelFitSpec(),
        marketing_processor.MarketingAnalysisSpec(
            media_summary_spec=marketing_processor.MediaSummarySpec(
                include_non_paid_channels=include_non_paid_channels,
            ),
        ),
        budget_opt_spec,
    ],
    time_breakdown_generators=time_breakdown_generators,
)

print('Converting to dataframes.')
dataframes = dataframe_model_converter.DataFrameModelConverter(mmm_proto)()

# ---------------------------------------------------------------------------
# UPLOAD - write to the existing target spreadsheet (not a new one each run).
# Strategy: try Meridian's native helper first if it supports targeting by ID; otherwise fall back to
# direct gspread upload. Most Meridian versions only support upload_to_gsheet(..., spreadsheet_name=...)
# which creates a NEW sheet, so the gspread fallback is the expected path.
# ---------------------------------------------------------------------------
print(f'Uploading to existing spreadsheet (id={TARGET_SPREADSHEET_ID})...')

_upload_params = set(inspect.signature(sheets.upload_to_gsheet).parameters.keys())
print(f"  sheets.upload_to_gsheet params: {sorted(_upload_params)}")
_native_id_param = next(
    (p for p in ('spreadsheet_id', 'sheet_id', 'existing_spreadsheet_id') if p in _upload_params),
    None,
)

spreadsheet = None
if _native_id_param:
    try:
        spreadsheet = sheets.upload_to_gsheet(
            dataframes, credentials,
            **{_native_id_param: TARGET_SPREADSHEET_ID},
        )
        print(f"  Updated via Meridian's native '{_native_id_param}' parameter.")
    except Exception as e:
        print(f"  Native upload via '{_native_id_param}' failed ({type(e).__name__}: {e}). Falling back to gspread.")
        spreadsheet = None

if spreadsheet is None:
    # Direct gspread upload to the target spreadsheet
    import gspread
    import pandas as pd
    import numpy as np

    try:
        gc = gspread.authorize(credentials)
    except Exception:
        # If the colab credentials object isn't directly acceptable, fall back to google.auth.default
        from google.auth import default as _default_creds
        _creds, _ = _default_creds(scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
        ])
        gc = gspread.authorize(_creds)

    spreadsheet = gc.open_by_key(TARGET_SPREADSHEET_ID)
    print(f"  Opened existing spreadsheet: '{spreadsheet.title}'")

    # The converter's output could be a dict, namedtuple, dataclass, or a plain object with DataFrame
    # attributes. Normalize to a list of (name, df) pairs.
    if isinstance(dataframes, dict):
        df_pairs = list(dataframes.items())
    elif hasattr(dataframes, '_asdict'):
        df_pairs = list(dataframes._asdict().items())
    elif hasattr(dataframes, '__dataclass_fields__'):
        df_pairs = [(f, getattr(dataframes, f)) for f in dataframes.__dataclass_fields__]
    else:
        df_pairs = [(k, v) for k, v in vars(dataframes).items() if hasattr(v, 'columns')]

    # -----------------------------------------------------------------------
    # AUGMENT: append a "Last 52 Weeks" row to ModelDiagnostics so the dashboard surfaces both the
    # full-window fit and the recent-year fit side-by-side. Meridian's native ModelFitSpec only reports
    # one row ("All Data") computed across the full ~174-week training window - that pulls down R² to
    # ~0.71 because many video partners weren't active in 2023/early-2024. The same model fits the most
    # recent 52 weeks at ~0.82 (per the HTML summary), which is what budget decisions actually rely on.
    # We compute the recent-window metrics here from the ModelFit weekly actuals/predictions using the
    # classical formulas (Meridian's R² is Bayesian R², slightly different methodology but typically
    # within ~1-2 pts of classical for a well-fit model). NOTE: this augmentation only applies on the
    # gspread fallback path - the native path uploads the raw `dataframes` object before we touch it.
    # -----------------------------------------------------------------------
    def _augment_diagnostics_with_recent_window(df_pairs, n_weeks=52):
        pairs = dict(df_pairs)
        if 'ModelDiagnostics' not in pairs or 'ModelFit' not in pairs:
            print(f"  (skip recent-window diagnostics: ModelDiagnostics/ModelFit tab not present)")
            return df_pairs

        fit = pairs['ModelFit'].copy()

        # Flexible column matching - Meridian's column names vary across versions.
        def _find_col(df, candidates):
            lookup = {c.lower(): c for c in df.columns}
            for cand in candidates:
                if cand in lookup:
                    return lookup[cand]
            return None

        time_col   = _find_col(fit, ['time', 'date', 'week', 'time_period', 'period'])
        actual_col = _find_col(fit, ['actual', 'actual_kpi', 'actual_revenue', 'realized', 'observed', 'y_true'])
        pred_col   = _find_col(fit, ['expected', 'predicted', 'expected_kpi', 'expected_revenue',
                                     'mean', 'prediction', 'fit', 'y_pred'])
        if time_col is None or actual_col is None or pred_col is None:
            print(f"  (skip recent-window diagnostics: couldn't identify time/actual/predicted cols in "
                  f"ModelFit; columns are {list(fit.columns)})")
            return df_pairs

        # Sort by time, take last N weeks
        fit[time_col] = pd.to_datetime(fit[time_col], errors='coerce')
        fit = fit.dropna(subset=[time_col, actual_col, pred_col]).sort_values(time_col)
        recent = fit.tail(n_weeks) if len(fit) >= n_weeks else fit
        actual = recent[actual_col].astype(float).to_numpy()
        pred   = recent[pred_col].astype(float).to_numpy()

        # Classical R² = 1 - SSE/SST; MAPE = mean(|err|/|actual|); wMAPE = sum|err|/sum|actual|.
        sse = float(np.sum((actual - pred) ** 2))
        sst = float(np.sum((actual - np.mean(actual)) ** 2))
        r_squared = 1.0 - (sse / sst) if sst > 0 else np.nan
        abs_err = np.abs(actual - pred)
        with np.errstate(divide='ignore', invalid='ignore'):
            mape_terms = np.where(actual != 0, abs_err / np.abs(actual), np.nan)
        mape  = float(np.nanmean(mape_terms))
        wmape = float(np.sum(abs_err) / np.sum(np.abs(actual))) if np.sum(np.abs(actual)) > 0 else np.nan

        # Build the new row matching existing column names (defensive on naming).
        diag = pairs['ModelDiagnostics'].copy()
        new_row = {col: '' for col in diag.columns}
        for col in diag.columns:
            cl = col.lower().strip()
            if 'dataset' in cl or cl in ('name', 'window'):
                new_row[col] = f'Last {n_weeks} Weeks'
            elif 'r' in cl and 'square' in cl:
                new_row[col] = r_squared
            elif cl == 'mape':
                new_row[col] = mape
            elif cl == 'wmape':
                new_row[col] = wmape

        pairs['ModelDiagnostics'] = pd.concat([diag, pd.DataFrame([new_row])], ignore_index=True)
        print(f"  Added 'Last {n_weeks} Weeks' row to ModelDiagnostics: "
              f"R²={r_squared:.4f}, MAPE={mape:.4f}, wMAPE={wmape:.4f} "
              f"(covering {recent[time_col].min().date()} -> {recent[time_col].max().date()})")
        return list(pairs.items())

    df_pairs = _augment_diagnostics_with_recent_window(df_pairs, n_weeks=52)

    # -----------------------------------------------------------------------
    # AUGMENT: build a sibling MediaROI_Aligned tab with spend-aligned (pulled-back) ROI per channel
    # per analysis period. The native MediaROI tab uses realized-period attribution: revenue *landing
    # in period P* / spend *in period P*. With max_lag=12 and binomial adstock spreading video revenue
    # across 10+ weeks, that's systematically wrong - especially for video where only ~14% of revenue
    # lands in the impression week (vs ~52% for geometric channels). The aligned tab attributes the
    # FULL lagged tail back to the spend that drove it, using the same `media_selected_times` trick as
    # the standalone spend-aligned ROAS-by-quarter cell. Schema matches MediaROI exactly so Looker
    # Studio data sources can be repointed with one click. Roughly 2-5 min cost (one incremental_outcome
    # + one marginal_roi call per analysis period; ~20-30 periods typical).
    # -----------------------------------------------------------------------
    from meridian.analysis import analyzer as _analyzer_module
    _analyzer  = _analyzer_module.Analyzer(mmm)
    _times     = pd.to_datetime(np.asarray(mmm.input_data.time.values))
    _paid_chs  = list(mmm.input_data.get_all_paid_channels())
    _spend_map = dict(zip(media_channels, media_spend_cols))

    def _build_media_roi_aligned(df_pairs):
        pairs = dict(df_pairs)
        if 'MediaROI' not in pairs:
            print(f"  (skip MediaROI_Aligned: MediaROI tab not present)")
            return df_pairs

        src = pairs['MediaROI'].copy()
        period_cols = ['Analysis Period', 'Analysis Date Start', 'Analysis Date End']
        if not all(c in src.columns for c in period_cols):
            print(f"  (skip MediaROI_Aligned: missing period cols. MediaROI columns: {list(src.columns)})")
            return df_pairs

        periods = src[period_cols].drop_duplicates().reset_index(drop=True)
        n_paid = len(_paid_chs)
        print(f"  Computing MediaROI_Aligned for {len(periods)} periods x {n_paid} channels...")

        new_rows = []
        for _, period in periods.iterrows():
            pname = period['Analysis Period']
            try:
                start = pd.to_datetime(period['Analysis Date Start'])
                end   = pd.to_datetime(period['Analysis Date End'])
            except Exception as e:
                print(f"    [{pname}] skip - bad date: {e}")
                continue

            wk_mask = (_times >= start) & (_times < end)
            if not wk_mask.any():
                print(f"    [{pname}] skip - no model weeks in {start.date()} -> {end.date()}")
                continue

            # Aligned incremental outcome: media ON only in period weeks, sum revenue over ALL weeks.
            try:
                inc_aligned = _analyzer.incremental_outcome(
                    media_selected_times=wk_mask.tolist(),
                    selected_times=None,
                    aggregate_geos=True,
                    aggregate_times=True,
                    include_non_paid_channels=False,
                ).numpy()  # (chains, draws, n_paid)
            except Exception as e:
                print(f"    [{pname}] skip - incremental_outcome failed: {type(e).__name__}: {e}")
                continue

            # Spend-aligned marginal ROI: Meridian's marginal_roi(selected_times=...) already uses
            # pulled-back semantics (it captures the full lagged response to a perturbation in spend
            # within the selected window). Fall back to NaN if the method isn't available or fails.
            mroi_mean = np.full(n_paid, np.nan)
            try:
                mroi_tensor = _analyzer.marginal_roi(
                    selected_times=wk_mask.tolist(),
                    aggregate_geos=True,
                    use_posterior=True,
                ).numpy()
                mroi_mean = mroi_tensor.mean(axis=(0, 1))
            except Exception as e:
                print(f"    [{pname}] marginal_roi failed ({type(e).__name__}: {e}); setting to NaN")

            aligned_mean = inc_aligned.mean(axis=(0, 1))
            aligned_lo   = np.percentile(inc_aligned,  5, axis=(0, 1))
            aligned_hi   = np.percentile(inc_aligned, 95, axis=(0, 1))

            period_df = df_bq[(df_bq['time'] >= start) & (df_bq['time'] < end)]

            for j, ch in enumerate(_paid_chs):
                spend_col = _spend_map.get(ch)
                spend_val = float(period_df[spend_col].sum()) if (spend_col in period_df.columns) else 0.0
                if spend_val > 0:
                    roi    = float(aligned_mean[j]) / spend_val
                    roi_lo = float(aligned_lo[j])   / spend_val
                    roi_hi = float(aligned_hi[j])   / spend_val
                else:
                    roi = roi_lo = roi_hi = np.nan

                # Preserve Effectiveness from MediaROI (it's just beta_m, unaffected by aligned vs
                # realized split - same posterior value either way).
                eff = ''
                match = src[(src['Channel'] == ch) & (src['Analysis Period'] == pname)]
                if not match.empty and 'Effectiveness' in match.columns:
                    eff = match['Effectiveness'].iloc[0]

                new_rows.append({
                    'Channel': ch,
                    'Spend': spend_val,
                    'Effectiveness': eff,
                    'ROI': roi,
                    'ROI CI Low': roi_lo,
                    'ROI CI High': roi_hi,
                    'Marginal ROI': float(mroi_mean[j]) if np.isfinite(mroi_mean[j]) else np.nan,
                    'Is Revenue KPI': True,
                    'Analysis Period': pname,
                    'Analysis Date Start': period['Analysis Date Start'],
                    'Analysis Date End': period['Analysis Date End'],
                })

        aligned_df = pd.DataFrame(new_rows)
        # Preserve MediaROI column ordering so tabs are visually parallel.
        ordered_cols = [c for c in src.columns if c in aligned_df.columns]
        aligned_df = aligned_df[ordered_cols + [c for c in aligned_df.columns if c not in ordered_cols]]
        pairs['MediaROI_Aligned'] = aligned_df
        print(f"  Built MediaROI_Aligned: {len(aligned_df)} rows x {len(aligned_df.columns)} cols")
        return list(pairs.items())

    df_pairs = _build_media_roi_aligned(df_pairs)

    print(f"  Writing {len(df_pairs)} dataframes to worksheets:")

    for sheet_name, df in df_pairs:
        # Google Sheets worksheet titles: max 100 chars, no '/' or '\' (and a few others); be defensive.
        safe_name = str(sheet_name).strip().replace('/', '_').replace('\\', '_')[:100]
        if not safe_name:
            safe_name = 'sheet_unnamed'

        # Find or create the worksheet
        try:
            ws = spreadsheet.worksheet(safe_name)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title=safe_name,
                rows=max(len(df) + 10, 100),
                cols=max(len(df.columns) + 5, 26),
            )

        # Convert DataFrame to gspread-friendly values: NaN/inf -> '', datetimes -> ISO strings, numerics
        # preserved as numbers (so Looker Studio sees them as numeric). Stringifying everything would
        # break any numeric formulas/aggregations downstream. NOTE: pandas .notna() treats inf as valid
        # (only catches NaN/None), but the JSON encoder rejects inf outright with "Out of range float
        # values are not JSON compliant". Scenario planner outputs produce inf wherever there's a
        # divide-by-zero (marginal ROI at zero spend, eff_per_input_unit when input=0, etc.), so we
        # replace inf/-inf with NaN first and then funnel the NaNs to ''.
        df_copy = df.copy()
        for _col in df_copy.select_dtypes(include=['datetime64', 'datetimetz']).columns:
            df_copy[_col] = df_copy[_col].dt.strftime('%Y-%m-%d %H:%M:%S')
        df_copy = df_copy.replace([np.inf, -np.inf], np.nan)
        df_copy = df_copy.astype(object).where(df_copy.notna(), '')

        values = [df_copy.columns.astype(str).tolist()] + df_copy.values.tolist()
        ws.update(range_name='A1', values=values)
        print(f"    - {safe_name}: {len(df)} rows x {len(df.columns)} cols")

print(f'\nDone. Spreadsheet URL: https://docs.google.com/spreadsheets/d/{TARGET_SPREADSHEET_ID}/edit')

# ---------------------------------------------------------------------------
# Scenario Planner exporter to Looker Studio (best-effort). url_generator expects Meridian's own
# spreadsheet object; if we went through the gspread fallback, it likely won't accept the gspread
# Spreadsheet object. Your existing dashboard pointed at this sheet will refresh automatically anyway.
# ---------------------------------------------------------------------------
try:
    report_url = url_generator.create_report_url(spreadsheet)
    HTML(f'<a href="{report_url}" target="_blank">Open ABC MMM Scenario Planner in Looker Studio</a>')
except Exception as e:
    print(f"\nLooker Studio URL not auto-generated (expected when using the gspread fallback path):")
    print(f"  {type(e).__name__}: {e}")
    print(f"Your existing dashboard pointed at this spreadsheet should refresh with the new data automatically.")
