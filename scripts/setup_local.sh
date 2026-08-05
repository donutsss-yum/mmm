#!/usr/bin/env bash
# =============================================================================
# One-time local environment setup (macOS / Linux).
#
# Creates .venv (Python 3.12 via uv) and installs requirements-local.txt -
# Meridian WITHOUT the CUDA extra (no NVIDIA GPU locally; TF runs on CPU).
#
# Usage:  ./scripts/setup_local.sh
# Then:   .venv/bin/python scripts/run_local.py 00     # preflight
# Docs:   docs/LOCAL.md
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' not found. Install it first:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

echo "=== Creating .venv (Python 3.12) ==="
uv venv --python 3.12 .venv

echo
echo "=== Installing requirements-local.txt (Meridian + TF CPU; several hundred MB) ==="
uv pip install --python .venv/bin/python -r requirements-local.txt

echo
echo "=== Done. Next steps ==="
echo "1. Google auth (once per machine, if not already done for the Colab CLI):"
echo "   see docs/SETUP.md - the single gcloud ADC command covers BigQuery, Drive,"
echo "   Sheets AND the Colab CLI."
echo "2. Preflight:      .venv/bin/python scripts/run_local.py 00"
echo "3. Full pipeline:  .venv/bin/python scripts/run_local.py"
