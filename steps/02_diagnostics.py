# @title Step 02 - Model diagnostics + single HTML report - takes about 3 min on A100
# =============================================================================
# MIGRATION NOTE: this is cell 1 of MMMv13_2.ipynb. In the notebook the
# diagnostic charts rendered inline; a terminal exec has no inline display, so
# every chart is now SAVED to a timestamped diagnostics folder on Drive:
#   /content/drive/MyDrive/ABC/MMM/diagnostics/<YYYYMMDD_HHMMSS>/
#   - Meridian visualizer charts (Altair) -> .html files (open in any browser)
#   - ArviZ trace/ESS plots (matplotlib)  -> .png files
# The numeric convergence summary (az.summary) still prints to stdout, which
# `colab exec` streams back to your terminal - eyeball r_hat (< 1.05) and
# ess_bulk there, then open the saved charts for anything suspicious.
#
# The main deliverable is unchanged: Meridian's two-page HTML results summary,
# written to the Drive folder with the same filename pattern as always.
#
# REQUIRES kernel state from step 01 (mmm, out_dir). Run via:
#   colab exec -s <session> -f steps/02_diagnostics.py --timeout 3600
# =============================================================================
import datetime
import os

_missing = [n for n in ('mmm', 'out_dir') if n not in globals()]
if _missing:
    raise RuntimeError(
        f"Missing kernel globals: {_missing}. Run steps/01_fit_model.py first "
        f"(or steps/load_model.py to restore a saved fit)."
    )

import arviz as az
import matplotlib
matplotlib.use('Agg')  # headless: never try to open a display
import matplotlib.pyplot as plt
from meridian.analysis import summarizer
from meridian.analysis import visualizer

# --- where diagnostics land -------------------------------------------------
_stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
diag_dir = os.path.join(out_dir, 'diagnostics', _stamp)
os.makedirs(diag_dir, exist_ok=True)
print(f"Diagnostics folder: {diag_dir}")


def _save_chart(chart, name):
    """Save a Meridian/Altair chart as standalone HTML; never let a save failure kill the step."""
    try:
        path = os.path.join(diag_dir, f"{name}.html")
        chart.save(path)
        print(f"  saved {path}")
    except Exception as e:
        print(f"  (could not save {name}: {type(e).__name__}: {e})")


def _save_current_figs(name):
    """Save all open matplotlib figures under a name prefix, then close them."""
    for num in plt.get_fignums():
        fig = plt.figure(num)
        path = os.path.join(diag_dir, f"{name}_{num}.png")
        try:
            fig.savefig(path, dpi=120, bbox_inches='tight')
            print(f"  saved {path}")
        except Exception as e:
            print(f"  (could not save {name} fig {num}: {type(e).__name__}: {e})")
    plt.close('all')


# 11) Diagnostics - same charts as the notebook, saved instead of displayed.
model_diagnostics = visualizer.ModelDiagnostics(mmm)
_save_chart(model_diagnostics.plot_rhat_boxplot(), 'rhat_boxplot')
_save_chart(model_diagnostics.plot_prior_and_posterior_distribution(parameter='roi_m'), 'prior_posterior_roi_m')
_save_chart(model_diagnostics.plot_prior_and_posterior_distribution(parameter='beta_m'), 'prior_posterior_beta_m')
_save_chart(model_diagnostics.plot_prior_and_posterior_distribution(parameter='beta_gm'), 'prior_posterior_beta_gm')
_save_chart(model_diagnostics.plot_prior_and_posterior_distribution(parameter='ec_m'), 'prior_posterior_ec_m')
_save_chart(visualizer.ModelFit(mmm).plot_model_fit(include_ci=True), 'model_fit')

inference_data = mmm.inference_data
parameters_to_plot = ['roi_m', 'beta_m', 'beta_gm', 'ec_m']
az.Numba.disable_numba()
for param in parameters_to_plot:
    az.plot_trace(
        inference_data,
        var_names=param,
        compact=False,
        backend_kwargs={"constrained_layout": True},
    )
    _save_current_figs(f'trace_{param}')

az.plot_ess(inference_data, kind='local', var_names=parameters_to_plot)
_save_current_figs('ess_local')

# Convergence table -> stdout (streams back to the local terminal). r_hat should be < 1.05.
print(az.summary(inference_data, var_names=parameters_to_plot))

# 12) Summary HTML export - the main deliverable, same location + naming as the notebook runs.
mmm_summarizer = summarizer.Summarizer(mmm)
start_date, end_date = '2025-06-29', '2026-06-21'  # REPORT WINDOW - should span 52 or 53 week-start days
now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
filename = f"v13_summary_output_{start_date}_to_{end_date}_{now}.html"

mmm_summarizer.output_model_results_summary(
    filename=filename,
    filepath=out_dir,
    start_date=start_date,
    end_date=end_date,
)
print(f"Model results saved to {out_dir}/{filename}")
