#!/usr/bin/env python3
"""Export the pipeline as a Colab-ready .ipynb (the "old fashioned way" escape hatch).

Generates a notebook whose cells are VERBATIM copies of the steps/ files, plus a
Colab-web-only setup cell (pip install, auth popup, Drive mount) up front. Upload the
result to colab.research.google.com (or open from Drive) and run top-to-bottom on a
GPU runtime - exactly like the pre-migration workflow.

    .venv/bin/python scripts/export_notebook.py                  # default stages
    .venv/bin/python scripts/export_notebook.py --stages 01 02   # subset
    .venv/bin/python scripts/export_notebook.py -o ~/my.ipynb    # explicit output

Default output: notebooks/exports/MMM_<branch>_<stamp>.ipynb  (gitignored - exports
are build artifacts; the steps/ files remain the source of truth).

Why the steps work unmodified in the Colab web UI: they are environment-aware.
`IS_COLAB` detects /content, `out_dir` resolves to the Drive mount, and
`google.auth.default()` picks up the credentials that `auth.authenticate_user()`
(setup cell) establishes. The GPU gate passes because Colab runtimes have a GPU.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

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
    # exp/v14-revenue-split branch only:
    '10':   'steps/10_exp_fit_split.py',
    '11':   'steps/11_exp_scorecard.py',
}
DEFAULT_STAGES = ['00', '01', 'save', '02', '03', '04']

SETUP_CELL = """\
# @title Setup - COLAB WEB UI ONLY (pip install + auth popup + Drive mount)
# This cell replaces what the CLI/local runners do outside the kernel. Run it first,
# once per runtime. Everything after it is a verbatim copy of the repo's steps/.
!pip -q install --upgrade google-meridian[colab,scenarioplanner,and-cuda]

from google.colab import auth, drive
credentials = auth.authenticate_user([
    'https://www.googleapis.com/auth/bigquery',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
])
drive.mount('/content/drive')
print('Setup complete - run the following cells in order.')\
"""


def _git(args):
    try:
        return subprocess.run(['git'] + args, cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return 'unknown'


def make_cell(source, cell_type='code'):
    lines = source.splitlines(keepends=True)
    if cell_type == 'code':
        return {'cell_type': 'code', 'source': lines, 'metadata': {},
                'execution_count': None, 'outputs': []}
    return {'cell_type': 'markdown', 'source': lines, 'metadata': {}}


def main():
    parser = argparse.ArgumentParser(description='Export pipeline steps as a Colab notebook.')
    parser.add_argument('--stages', nargs='+', default=DEFAULT_STAGES,
                        help=f"stages to include, in order (default: {' '.join(DEFAULT_STAGES)}; "
                             f"valid: {' '.join(STAGE_FILES)})")
    parser.add_argument('-o', '--output', default=None, help='output .ipynb path')
    args = parser.parse_args()

    unknown = [s for s in args.stages if s not in STAGE_FILES]
    if unknown:
        parser.error(f"unknown stage(s): {' '.join(unknown)}. Valid: {' '.join(STAGE_FILES)}")

    branch = _git(['rev-parse', '--abbrev-ref', 'HEAD'])
    commit = _git(['rev-parse', '--short', 'HEAD'])
    dirty = ' (uncommitted changes!)' if _git(['status', '--porcelain']) else ''
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

    provenance = (
        f"# ABC MMM pipeline - Colab export\n\n"
        f"Generated from git branch **`{branch}`** @ `{commit}`{dirty} "
        f"on {stamp} by `scripts/export_notebook.py`.\n\n"
        f"Stages included: {', '.join(args.stages)}.\n\n"
        f"**The repo's `steps/` files are the source of truth** - edits made here will "
        f"NOT flow back to git. Re-export after changing the repo. Run cells top to "
        f"bottom on a GPU runtime (Runtime > Change runtime type > A100)."
    )

    cells = [make_cell(provenance, 'markdown'), make_cell(SETUP_CELL)]
    for st in args.stages:
        path = os.path.join(REPO, STAGE_FILES[st])
        with open(path, 'r') as f:
            cells.append(make_cell(f.read().rstrip('\n')))

    nb = {
        'nbformat': 4,
        'nbformat_minor': 0,
        'metadata': {
            'kernelspec': {'name': 'python3', 'display_name': 'Python 3'},
            'language_info': {'name': 'python'},
            'colab': {'provenance': [], 'gpuType': 'A100', 'toc_visible': True},
            'accelerator': 'GPU',
        },
        'cells': cells,
    }

    out = args.output
    if out is None:
        out_dir = os.path.join(REPO, 'notebooks', 'exports')
        os.makedirs(out_dir, exist_ok=True)
        safe_branch = branch.replace('/', '-')
        out = os.path.join(out_dir, f"MMM_{safe_branch}_{stamp}.ipynb")
    out = os.path.expanduser(out)

    with open(out, 'w') as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
    print(f"Wrote {out}")
    print(f"  {len(cells)} cells: provenance + setup + {len(args.stages)} stage(s) "
          f"[{', '.join(args.stages)}] from {branch}@{commit}{dirty}")
    print("Upload to colab.research.google.com (File > Upload notebook), pick a GPU "
          "runtime, and run top to bottom.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
