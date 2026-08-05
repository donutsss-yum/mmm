#!/usr/bin/env bash
# =============================================================================
# Stop the Colab session and release the VM (stops compute-unit billing).
#
# Usage:            ./scripts/teardown.sh
# Env overrides:    MMM_SESSION=mmm   session name (default: mmm)
#
# WARNING: stopping kills the kernel, which wipes the fitted model from memory.
# If you'll want the fit later, make sure steps/save_model.py ran first
# (the default ./scripts/run_pipeline.sh includes it right after the fit).
# =============================================================================
set -euo pipefail

SESSION="${MMM_SESSION:-mmm}"

if ! command -v colab >/dev/null 2>&1; then
  echo "ERROR: 'colab' CLI not found on PATH. Install: uv tool install google-colab-cli"
  exit 1
fi

echo "=== Stopping session '$SESSION' ==="
colab stop -s "$SESSION"
echo "=== Done. Verify nothing is still burning compute units: ==="
colab sessions
