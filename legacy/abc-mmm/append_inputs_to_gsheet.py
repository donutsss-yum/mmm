"""Monthly append of ABC MMM input files into the 'ABC MMM Inputs' Google Sheet.

Usage:
    python3 append_inputs_to_gsheet.py "June 2026 Inputs" [--dry-run]

The argument is a subfolder of ./inputs (e.g. "May 2026 inputs"); filenames inside may carry
browser-download suffixes like "Emails (3).xlsx" - they're glob-matched. Read UPDATING_INPUTS.md
before running: it documents the per-tab rules, the incident history behind them, and the tabs
this script must never touch. Append-only by design (Ken's call); dedupe keys vary per tab:
date cutoff for daily series, Campaign ID for emails, full-row multiset for celeb events.
"""
import glob
import os
import sys
import warnings
warnings.filterwarnings('ignore')

import openpyxl
import gspread
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials

SHEET_ID = '1CeHZVQrONTRGb2_h4mmBYefX96Of4h8Ul1C5yx0Tb7I'
SA_PATH = os.path.expanduser('~/.config/gcloud/jelly-bq-sa.json')
INPUTS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inputs')
EPOCH = datetime(1899, 12, 30)   # Excel/Sheets serial epoch

WEEKDAYS = {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'}

# Weekday-weighted lightning-sale scoring used by the tab since inception (Sun..Sat -> 10,11,12,13,14,21,20)
LS_DAYS_FORMULA = (
    '=IF(OR(B{n}<>"Yes", A{n}=""), 0,\n'
    '    IFS(\n'
    '        WEEKDAY(A{n})=1,10,\n'
    '        WEEKDAY(A{n})=2,11,\n'
    '        WEEKDAY(A{n})=3,12,\n'
    '        WEEKDAY(A{n})=4,13,\n'
    '        WEEKDAY(A{n})=5,14,\n'
    '        WEEKDAY(A{n})=6,21,\n'
    '        WEEKDAY(A{n})=7,20\n'
    '    )\n)'
)


def to_serial(dt):
    return (dt - EPOCH).days if isinstance(dt, datetime) else None


def date_str(serial):
    return (EPOCH + timedelta(days=int(serial))).strftime('%-m/%-d/%Y')


def connect():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file(SA_PATH, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SHEET_ID)


def find_file(folder, pattern):
    """Match 'Emails*.xlsx' style patterns; tolerates ' (3)' download suffixes. None if absent."""
    hits = sorted(glob.glob(os.path.join(folder, pattern)))
    hits = [h for h in hits if not os.path.basename(h).startswith('~$')]
    if len(hits) > 1:
        # Prefer the most recently modified copy when multiple downloads are present
        hits.sort(key=os.path.getmtime, reverse=True)
        print(f'  note: {len(hits)} files match {pattern!r}, using {os.path.basename(hits[0])!r}')
    return hits[0] if hits else None


def read_xlsx(path, sheet, header_row=0):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = [list(r) for i, r in enumerate(ws.iter_rows(values_only=True)) if i > header_row]
    wb.close()
    return rows


def last_date_serial(ws, col='A'):
    vals = ws.get(f'{col}1:{col}{ws.row_count}', value_render_option='UNFORMATTED_VALUE')
    serials = [r[0] for r in vals[1:] if r and isinstance(r[0], (int, float))]
    return max(serials) if serials else 0


def blank_if_dash(v):
    """BQ external tables type these columns: numbers or blank only, never '-' placeholders."""
    return '' if v is None or v == '-' else v


# ----------------------------------------------------------------------------------------------------
# Per-tab handlers. Each returns (rows_to_append, start_row) without writing when dry_run is set.
# ----------------------------------------------------------------------------------------------------

def repair_trailing_blanks(ws, tab, src_by_serial, n_metrics, dry):
    """Exports end before the data does, so a tab can hold trailing rows with a date but blank metrics
    (from an earlier month's append). Once a later file carries values for those dates, fill them in
    place - the date-cutoff dedupe would otherwise skip them forever. Interior blanks (e.g. Easter,
    store closures) stay blank because the source is blank too."""
    last_col = chr(65 + n_metrics)   # metrics live in B..(B+n_metrics-1)
    vals = ws.get(f'A1:{last_col}{ws.row_count}', value_render_option='UNFORMATTED_VALUE')
    trailing = []
    for i in range(len(vals) - 1, 0, -1):
        r = list(vals[i]) + [''] * (1 + n_metrics - len(vals[i]))
        if not isinstance(r[0], (int, float)):
            break
        if any(v not in ('', None) for v in r[1:1 + n_metrics]):
            break
        trailing.append((i + 1, int(r[0])))
    for row_num, serial in trailing:
        src_vals = src_by_serial.get(serial)
        if src_vals and any(v != '' for v in src_vals):
            if dry:
                print(f'{tab}: would repair blank row {row_num} ({date_str(serial)}) with {src_vals}')
            else:
                ws.update(values=[src_vals], range_name=f'B{row_num}:{last_col}{row_num}',
                          value_input_option='USER_ENTERED')
                print(f'{tab}: repaired blank row {row_num} ({date_str(serial)}) with {src_vals}')


def truncate_trailing_blanks(new_rows, first_metric=1):
    """Never append rows whose metrics are all blank at the batch tail - Ken deletes them, and they
    spring the backfill trap that repair_trailing_blanks exists to fix."""
    while new_rows and all(v == '' for v in new_rows[-1][first_metric:]):
        new_rows.pop()
    return new_rows


def do_storecount(sh, path, dry):
    ws = sh.worksheet('control_storecount')
    # Source mixes year-rollup rows ('2024', 45618) into col A - only real datetimes are data rows
    src = {to_serial(r[0]): [blank_if_dash(r[1])] for r in read_xlsx(path, 'Sheet1')
           if isinstance(r[0], datetime)}
    repair_trailing_blanks(ws, 'control_storecount', src, n_metrics=1, dry=dry)
    cutoff = last_date_serial(ws)
    start = len(ws.get_all_values()) + 1
    new = truncate_trailing_blanks(sorted((s, v[0]) for s, v in src.items() if s > cutoff))
    out = [[date_str(s), stores, f'=B{start + i}/7'] for i, (s, stores) in enumerate(new)]
    report('control_storecount', out, lambda: ws.append_rows(out, value_input_option='USER_ENTERED'), dry)


def do_lightning(sh, path, dry):
    ws = sh.worksheet('control_lightning')
    cutoff = last_date_serial(ws)
    start = len(ws.get_all_values()) + 1
    new = sorted((to_serial(r[0]), r[2] if r[2] else '') for r in read_xlsx(path, 'Sheet1')
                 if isinstance(r[0], datetime) and to_serial(r[0]) > cutoff)
    out = [[date_str(s), ls, LS_DAYS_FORMULA.replace('{n}', str(start + i))] for i, (s, ls) in enumerate(new)]
    report('control_lightning', out, lambda: ws.append_rows(out, value_input_option='USER_ENTERED'), dry)


def do_celebs(sh, path, dry):
    """Full-row multiset reconcile, NOT a date cutoff: events land retroactively, Ken hand-edits this
    tab, and one event with N product Pcodes is intentionally N identical rows (source Pcode dropped)."""
    ws = sh.worksheet('control_celebs')
    tab = [r for r in ws.get_all_values() if any(c.strip() for c in r)]

    def norm_tab_date(s):
        for fmt in ('%m/%d/%y', '%m/%d/%Y'):
            try:
                return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
            except ValueError:
                pass
        return s.strip()

    tab_rows = Counter((norm_tab_date(r[0]),) + tuple(c.strip() for c in r[1:5]) for r in tab[1:])
    src_rows = Counter()
    src_serial = {}
    for r in read_xlsx(path, 'Sheet1'):
        if not isinstance(r[1], datetime):
            continue
        key = (r[1].strftime('%Y-%m-%d'),) + tuple(str(v or '').strip() for v in r[2:6])
        src_rows[key] += 1
        src_serial[key] = to_serial(r[1])

    missing = src_rows - tab_rows      # in source, absent (or under-counted) in tab -> insert these
    extra = tab_rows - src_rows        # in tab only -> warn, never delete (may predate this export)
    for k, n in extra.items():
        print(f'  warn: control_celebs has {n}x row not in source (leaving alone): {k}')

    to_insert = sorted((src_serial[k], k, n) for k, n in missing.items())
    if dry:
        for s, k, n in to_insert:
            print(f'  would insert {n}x {k}')
        report('control_celebs', [k for _, k, n in to_insert for _ in range(n)], None, dry)
        return
    inserted = 0
    for s, key, n in to_insert:
        iso, store, etype, brand, celeb = key
        row_vals = [date_str(s), store, etype, brand, celeb]
        for _ in range(n):
            # Keep chronological order: insert after the last existing row with date <= this one
            tab = [r for r in ws.get_all_values() if any(c.strip() for c in r)]
            pos = 1
            for i, r in enumerate(tab[1:], start=2):
                d = norm_tab_date(r[0])
                if d and d <= iso:
                    pos = i
            ws.insert_row(row_vals, pos + 1, value_input_option='USER_ENTERED')
            inserted += 1
    print(f'control_celebs: inserted {inserted} rows')


EMAIL_NCOLS = 33
# A shifted source row (Incident #1, June 2026) lacks the five rate columns; everything from Total
# Opens onward sits 5 left. Map shifted index -> schema index. Rates (7-11) stay blank: they are not
# derivable from counts (Klaviyo rates are unique-based).
EMAIL_SHIFT_REMAP = {**{k: k for k in range(7)}, **{k: k + 5 for k in range(7, 28)}}


def email_row_is_shifted(r):
    """In a correct row, index 25 is the Subject line; in a shifted row it's Campaign Channel."""
    return str(r[25] or '').strip() == 'Email'


def do_email(sh, path, dry):
    ws = sh.worksheet('control_email')
    tab = ws.get_all_values()
    existing_ids = {r[2].strip() for r in tab[1:] if len(r) > 2 and r[2].strip()}
    start = len(tab) + 1

    src = read_xlsx(path, 'Sheet1')
    batch = []
    for r in src:
        if len(r) != EMAIL_NCOLS:
            sys.exit(f'ABORT: Emails.xlsx row has {len(r)} cols, expected {EMAIL_NCOLS} - schema changed, '
                     f'inspect the file and update this script/UPDATING_INPUTS.md')
        if not isinstance(r[4], datetime) or str(r[2]).strip() in existing_ids:
            continue
        if email_row_is_shifted(r):
            row = [''] * EMAIL_NCOLS
            for s_i, t_i in EMAIL_SHIFT_REMAP.items():
                row[t_i] = r[s_i] if r[s_i] is not None else ''
            if row[29] not in WEEKDAYS:   # remap must land Day of Week where the schema expects it
                sys.exit(f'ABORT: shifted-row remap failed sanity check for campaign {r[2]}: '
                         f'Day of Week slot holds {row[29]!r}')
        else:
            # Correct layout: verify semantics anyway - a rate slot holding a count means a NEW kind of
            # mangling that the shift detector doesn't cover. Fail loudly rather than paste garbage.
            if isinstance(r[7], (int, float)) and r[7] > 1.5:
                sys.exit(f'ABORT: campaign {r[2]}: Open Rate slot holds {r[7]} (>1) but row does not '
                         f'match the known shifted layout - inspect the file')
            row = [v if v is not None else '' for v in r]
        sd = r[4]
        row[4] = sd.strftime('%-m/%-d/%Y')
        row[5] = row[5].strftime('%-I:%M %p') if hasattr(row[5], 'strftime') else (row[5] or '')
        if row[29] == '':
            row[29] = sd.strftime('%A')
        if row[30] == '':
            row[30] = 'Email'   # 100% of tab history is 'Email'
        batch.append((to_serial(sd), str(r[2]).strip(), row))

    batch.sort(key=lambda x: (x[0], x[1]))   # real date order, never string order
    out = [row for _, _, row in batch]

    def write():
        ws.append_rows(out, value_input_option='USER_ENTERED')
        end = start + len(out) - 1
        ws.format(f'F{start}:F{end}', {'numberFormat': {'type': 'TIME', 'pattern': 'h:mm am/pm'}})
        # '#N/A' Email Type is literal text in this tab; USER_ENTERED converts it to an error value
        for i, row in enumerate(out):
            if str(row[32]).strip() == '#N/A':
                ws.update(values=[['#N/A']], range_name=f'AG{start + i}', value_input_option='RAW')

    report('control_email', out, write, dry)


def do_rev_store(sh, path, dry):
    ws = sh.worksheet('rev_store')
    cutoff = last_date_serial(ws)
    agg = defaultdict(lambda: [0.0, 0, 0])
    # Real header is xlsx row 3; rows are per-store per-day plus a 'Total' row - datetime check skips both
    for r in read_xlsx(path, 'Store Sales', header_row=2):
        if not isinstance(r[0], datetime):
            continue
        s = to_serial(r[0])
        if s <= cutoff:
            continue
        try:
            agg[s][0] += float(r[2] or 0)
            agg[s][1] += int(r[6] or 0)
            agg[s][2] += int(r[14] or 0)
        except (ValueError, TypeError):
            pass
    out = [[date_str(s), round(v[0], 2), v[1], v[2]] for s, v in sorted(agg.items())]
    report('rev_store', out, lambda: ws.append_rows(out, value_input_option='USER_ENTERED'), dry)


def do_rev_simple(sh, tab, path, xlsx_sheet, dry):
    """rev_ecom / rev_app / rev_vault: keep Date + List Price/Orders/Units (cols 3/4/5), drop Gross/Net."""
    ws = sh.worksheet(tab)
    src = {to_serial(r[0]): [blank_if_dash(r[3]), blank_if_dash(r[4]), blank_if_dash(r[5])]
           for r in read_xlsx(path, xlsx_sheet) if isinstance(r[0], datetime)}
    repair_trailing_blanks(ws, tab, src, n_metrics=3, dry=dry)
    cutoff = last_date_serial(ws)
    new = truncate_trailing_blanks(sorted((s, *v) for s, v in src.items() if s > cutoff))
    out = [[date_str(r[0])] + list(r[1:]) for r in new]
    report(tab, out, lambda: ws.append_rows(out, value_input_option='USER_ENTERED'), dry)


def report(tab, out, write_fn, dry):
    span = f" ({out[0][0]} to {out[-1][0]})" if out and isinstance(out[0], list) else ''
    if dry:
        print(f'{tab}: would append {len(out)} rows{span}')
    elif out:
        write_fn()
        print(f'{tab}: appended {len(out)} rows{span}')
    else:
        print(f'{tab}: nothing new')


# ----------------------------------------------------------------------------------------------------
# Post-write verification: semantic checks on live tab tails. Catches type garbage the append itself
# can't (rule 3 in UPDATING_INPUTS.md: matching a malformed source proves nothing).
# ----------------------------------------------------------------------------------------------------

def verify(sh):
    print('\n--- verification ---')
    problems = 0
    ws = sh.worksheet('control_email')
    tail = ws.get(f'A2:AG{len(ws.get_all_values())}', value_render_option='UNFORMATTED_VALUE')
    for i, r in enumerate(tail, start=2):
        pad = list(r) + [''] * (EMAIL_NCOLS - len(r))
        rate = pad[20]   # U: Placed Order Rate - numeric-or-blank, and never a plausible text leak
        if rate != '' and not isinstance(rate, (int, float)):
            print(f'  control_email row {i}: U (Placed Order Rate) is text: {str(rate)[:40]!r}')
            problems += 1
        if str(pad[25]).strip() == 'Email':   # Subject slot holding 'Email' = the shift signature
            print(f'  control_email row {i}: Z (Subject) reads "Email" - shifted row')
            problems += 1
    for tab in ['control_storecount', 'control_lightning', 'control_celebs',
                'rev_store', 'rev_ecom', 'rev_app', 'rev_vault']:
        ws = sh.worksheet(tab)
        vals = [r for r in ws.get_all_values() if any(c.strip() for c in r)]
        bad = [r[0] for r in vals[1:] if r[0].strip() and not any(ch in r[0] for ch in '/-')]
        if bad:
            print(f'  {tab}: {len(bad)} col-A values not date-like (raw serials?): {bad[:3]}')
            problems += 1
        print(f'  {tab}: {len(vals) - 1} data rows, last date {vals[-1][0]}')
    print(f'verification: {"CLEAN" if problems == 0 else str(problems) + " PROBLEMS - fix before BQ reads this"}')


def main():
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    dry = '--dry-run' in sys.argv
    if not args:
        folders = sorted((d for d in glob.glob(os.path.join(INPUTS_ROOT, '*')) if os.path.isdir(d)),
                         key=os.path.getmtime, reverse=True)
        sys.exit('Usage: python3 append_inputs_to_gsheet.py "<folder under inputs/>" [--dry-run]\n'
                 + 'Folders found: ' + ', '.join(os.path.basename(f) for f in folders))
    folder = os.path.join(INPUTS_ROOT, args[0])
    if not os.path.isdir(folder):
        sys.exit(f'No such folder: {folder}')

    files = {
        'storecount': find_file(folder, 'Count of store*.xlsx'),
        'lightning': find_file(folder, 'Lighting Sale Days*.xlsx'),
        'celebs': find_file(folder, 'Store Event Data*.xlsx'),
        'email': find_file(folder, 'Emails*.xlsx'),
        'sales': find_file(folder, 'Sales by Day*.xlsx'),
    }
    known = {os.path.basename(p) for p in files.values() if p}
    for f in sorted(glob.glob(os.path.join(folder, '*.xlsx'))):
        if os.path.basename(f) not in known:
            print(f'SKIPPING unrecognized file (ask Ken if it should be loaded): {os.path.basename(f)}')
    for k, v in files.items():
        if v is None:
            print(f'note: no file for {k} this month')

    sh = connect()
    if files['storecount']:
        do_storecount(sh, files['storecount'], dry)
    if files['lightning']:
        do_lightning(sh, files['lightning'], dry)
    if files['celebs']:
        do_celebs(sh, files['celebs'], dry)
    if files['email']:
        do_email(sh, files['email'], dry)
    if files['sales']:
        do_rev_store(sh, files['sales'], dry)
        do_rev_simple(sh, 'rev_ecom', files['sales'], 'ABCFWS sales', dry)
        do_rev_simple(sh, 'rev_app', files['sales'], 'App Sales', dry)
        do_rev_simple(sh, 'rev_vault', files['sales'], 'Vault Sales', dry)

    if not dry:
        verify(sh)
    print('\nDone. Update the History table in UPDATING_INPUTS.md.')


if __name__ == '__main__':
    main()
