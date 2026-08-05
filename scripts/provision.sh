#!/usr/bin/env bash
# =============================================================================
# Provision a Colab GPU session for the ABC MMM pipeline.
#
# Usage:            ./scripts/provision.sh
# Env overrides:    MMM_SESSION=mmm   session name (default: mmm)
#                   MMM_GPU=A100      GPU type: T4|L4|G4|H100|A100 (default: A100)
#
# What it does:
#   1. colab new -s $MMM_SESSION --gpu $MMM_GPU     (allocates a billable VM!)
#   2. colab install -r requirements-colab.txt      (Meridian + deps, ~2-4 min)
#   3. colab auth + colab drivemount                (ONLY if run from a real
#      terminal - both are interactive browser flows a human must complete.
#      When run non-interactively, prints the two commands for you to run.)
#
# NOTE: the VM bills compute units until you run ./scripts/teardown.sh - the
# CLI's keep-alive daemon deliberately prevents idle timeout.
# =============================================================================
set -euo pipefail

SESSION="${MMM_SESSION:-mmm}"
GPU="${MMM_GPU:-A100}"

cd "$(dirname "$0")/.."

if ! command -v colab >/dev/null 2>&1; then
  echo "ERROR: 'colab' CLI not found on PATH."
  echo "Install it with:  uv tool install google-colab-cli"
  echo "Then authenticate per docs/SETUP.md (gcloud ADC with the 4 required scopes)."
  exit 1
fi

echo "=== Provisioning session '$SESSION' with GPU $GPU ==="
colab new -s "$SESSION" --gpu "$GPU"

echo
echo "=== Installing dependencies on the VM (requirements-colab.txt) ==="
colab install -s "$SESSION" -r requirements-colab.txt

echo
if [ -t 0 ]; then
  # Real terminal: run the two interactive auth flows inline.
  echo "=== Authenticating VM for Google services (browser flow) ==="
  colab auth -s "$SESSION"
  echo
  echo "=== Mounting Google Drive on the VM (browser flow) ==="
  colab drivemount -s "$SESSION"
  echo
  echo "=== Session '$SESSION' is fully ready ==="
  echo "Next:  ./scripts/run_pipeline.sh"
else
  # Non-interactive (e.g. driven by an agent): these two REQUIRE a human TTY.
  echo "=== VM is up, but two INTERACTIVE steps remain (human required) ==="
  echo "Run these yourself in a terminal, then continue:"
  echo "    colab auth -s $SESSION"
  echo "    colab drivemount -s $SESSION"
  echo "Then verify with:  ./scripts/run_pipeline.sh 00"
fi
