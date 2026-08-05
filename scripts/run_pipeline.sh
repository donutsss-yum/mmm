#!/usr/bin/env bash
# =============================================================================
# Run MMM pipeline stages on the Colab session via `colab exec`.
#
# Usage:
#   ./scripts/run_pipeline.sh                 # default: 00 01 save 02 03 04
#   ./scripts/run_pipeline.sh 00              # preflight only
#   ./scripts/run_pipeline.sh 02 03 04        # re-run analyses (model in kernel)
#   ./scripts/run_pipeline.sh load 03         # restore saved fit, then stage 03
#   ./scripts/run_pipeline.sh 05              # scenario planner (EXPLICIT ONLY -
#                                             #  writes to the LIVE dashboard sheet)
# Env overrides:
#   MMM_SESSION=mmm    session name (default: mmm)
#
# Notes:
#   - Stage 05 is NEVER part of the default run: it overwrites worksheets in the
#     production dashboard spreadsheet that Looker Studio reads.
#   - Kernel state persists between stages (same Jupyter kernel across execs),
#     so 02-05 rely on globals created by 01 (or 'load').
#   - Timeouts are per-stage wall-clock caps for `colab exec` (its default is a
#     useless 30s). They are generous; a stage that exceeds one is genuinely stuck.
#   - Written for macOS's ancient bash 3.2: no associative arrays.
# =============================================================================
set -euo pipefail

SESSION="${MMM_SESSION:-mmm}"
cd "$(dirname "$0")/.."

if ! command -v colab >/dev/null 2>&1; then
  echo "ERROR: 'colab' CLI not found on PATH. Install: uv tool install google-colab-cli"
  exit 1
fi

stage_file() {
  case "$1" in
    00)   echo "steps/00_check_runtime.py" ;;
    01)   echo "steps/01_fit_model.py" ;;
    save) echo "steps/save_model.py" ;;
    load) echo "steps/load_model.py" ;;
    02)   echo "steps/02_diagnostics.py" ;;
    03)   echo "steps/03_roas_quarterly.py" ;;
    04)   echo "steps/04_decay_profiles.py" ;;
    05)   echo "steps/05_scenario_planner.py" ;;
    *)    echo "" ;;
  esac
}

stage_timeout() {
  case "$1" in
    00)   echo 300 ;;      # preflight: seconds
    01)   echo 7200 ;;     # fit: ~8 min typical on A100, cap at 2h
    save) echo 3600 ;;     # pickle to Drive can be slow for 60k draws
    load) echo 3600 ;;     # BQ pull + unpickle
    02)   echo 3600 ;;     # diagnostics + HTML report: ~3 min typical
    03)   echo 7200 ;;     # 2 counterfactuals per quarter
    04)   echo 3600 ;;     # 9 counterfactuals
    05)   echo 21600 ;;    # scenario planner: ~1.5h typical, cap at 6h
    *)    echo 3600 ;;
  esac
}

# bash 3.2 (macOS default) errors on empty-array expansion under `set -u`,
# so branch on $# instead of inspecting an assigned-but-empty array.
if [ $# -eq 0 ]; then
  STAGES=(00 01 save 02 03 04)
  echo "No stages given - running default pipeline: ${STAGES[*]}"
  echo "(Stage 05 / scenario planner is excluded by design: it writes to the live dashboard sheet.)"
else
  STAGES=("$@")
fi

# Validate all stage names before touching the (billable) session.
for st in "${STAGES[@]}"; do
  if [ -z "$(stage_file "$st")" ]; then
    echo "ERROR: unknown stage '$st'. Valid: 00 01 save load 02 03 04 05"
    exit 2
  fi
done

overall_start=$(date +%s)
for st in "${STAGES[@]}"; do
  f="$(stage_file "$st")"
  t="$(stage_timeout "$st")"
  echo
  echo "=== Stage $st: $f (session '$SESSION', timeout ${t}s) ==="
  start=$(date +%s)
  colab exec -s "$SESSION" -f "$f" --timeout "$t"
  echo "=== Stage $st finished in $(( $(date +%s) - start ))s ==="
done

echo
echo "=== All stages done in $(( $(date +%s) - overall_start ))s ==="
echo "Outputs are in Drive: My Drive/ABC/MMM/"
echo "Remember: ./scripts/teardown.sh when you're finished (the VM bills until stopped)."
