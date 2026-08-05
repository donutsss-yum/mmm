#!/usr/bin/env python3
"""Run MMM pipeline stages LOCALLY, in one shared namespace.

This is the local twin of scripts/run_pipeline.sh. On Colab, stages run inside a
persistent Jupyter kernel and share globals (mmm, df_bq, ...). Locally, this
script provides the same semantics: every stage executes in ONE shared Python
namespace within ONE process.

    .venv/bin/python scripts/run_local.py                # default: 00 01 save 02 03 04
    .venv/bin/python scripts/run_local.py 00             # preflight only
    .venv/bin/python scripts/run_local.py load 03 04     # restore saved fit, re-run analyses
    .venv/bin/python scripts/run_local.py 05             # scenario planner (EXPLICIT ONLY -
                                                         #   writes the LIVE dashboard sheet)

IMPORTANT: state dies when this process exits. Chain everything you need in ONE
invocation, or rely on 'save'/'load' (model persisted to the synced Drive
folder) to bridge invocations. There is no idle-billing concern locally - the
only cost of a long chain is your laptop's time.

Environment:
  - Sets MMM_ALLOW_CPU=1 (no CUDA on a Mac; the CPU fit is the point). Pass
    --require-gpu to override.
  - Outputs go to the desktop-synced Google Drive folder (see steps/01), or
    wherever --out-dir / MMM_OUT_DIR points.

Setup (once): ./scripts/setup_local.sh  — then see docs/LOCAL.md.
"""
import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STAGE_FILES = {
    '00':   'steps/00_check_runtime.py',
    '01':   'steps/01_fit_model.py',
    'save': 'steps/save_model.py',
    'load': 'steps/load_model.py',
    '02':   'steps/02_diagnostics.py',
    '03':   'steps/03_roas_quarterly.py',
    '04':   'steps/04_decay_profiles.py',
    '05':   'steps/05_scenario_planner.py',
}
DEFAULT_STAGES = ['00', '01', 'save', '02', '03', '04']  # 05 is explicit-only (live dashboard)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Run MMM pipeline stages locally in one shared namespace.',
        epilog=f"Stages: {' '.join(STAGE_FILES)}. Default: {' '.join(DEFAULT_STAGES)} "
               f"(05/scenario planner is explicit-only: it overwrites the live dashboard sheet).")
    parser.add_argument('stages', nargs='*', default=None,
                        help='stages to run, in order (default: %s)' % ' '.join(DEFAULT_STAGES))
    parser.add_argument('--out-dir', default=None,
                        help='override the output folder (sets MMM_OUT_DIR)')
    parser.add_argument('--require-gpu', action='store_true',
                        help='fail instead of allowing a CPU fit (default: CPU allowed locally)')
    args = parser.parse_args()

    stages = args.stages or DEFAULT_STAGES
    if not args.stages:
        print(f"No stages given - running default pipeline: {' '.join(stages)}")
        print("(Stage 05 / scenario planner is excluded by design: it writes to the live dashboard sheet.)")

    unknown = [s for s in stages if s not in STAGE_FILES]
    if unknown:
        parser.error(f"unknown stage(s): {' '.join(unknown)}. Valid: {' '.join(STAGE_FILES)}")

    if args.out_dir:
        os.environ['MMM_OUT_DIR'] = args.out_dir
    if not args.require_gpu:
        os.environ.setdefault('MMM_ALLOW_CPU', '1')

    # One namespace for every stage = the "kernel". Steps read/write globals here.
    ns: dict = {'__name__': '__main__'}

    overall_start = time.time()
    for st in stages:
        path = os.path.join(REPO, STAGE_FILES[st])
        print(f"\n=== Stage {st}: {STAGE_FILES[st]} (local) ===", flush=True)
        start = time.time()
        with open(path, 'r') as f:
            code = compile(f.read(), path, 'exec')
        try:
            exec(code, ns)  # noqa: S102 - deliberate: stages are trusted repo files
        except BaseException:
            print(f"\n=== Stage {st} FAILED after {time.time() - start:,.0f}s - aborting "
                  f"remaining stages ===", file=sys.stderr, flush=True)
            raise
        print(f"=== Stage {st} finished in {time.time() - start:,.0f}s ===", flush=True)

    print(f"\n=== All stages done in {time.time() - overall_start:,.0f}s ===")
    print("Outputs are in the synced Drive folder (My Drive/ABC/MMM/) unless --out-dir was set.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
