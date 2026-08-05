# HANDOFF: ABC MMM Monthly Input Updates

You (the session reading this) are taking over the recurring job of loading Ken's monthly input
files into the **ABC MMM Inputs** Google Sheet. This doc is your orientation; the deep runbook
with every rule and the incident history is `UPDATING_INPUTS.md` in this folder. **Read that file
completely before your first run.** Everything in it was learned from real mistakes across four
monthly rounds (March-June 2026), including one silent data-corruption incident that only Ken's
eyeball caught. Do not improvise around it.

## The task

Roughly monthly, Ken drops a folder like `inputs/July 2026 Inputs/` into `/Users/ken/cc/abc-mmm/`
and says something like "new files for the mix model, bring them into the gSheet." Your job:

1. `cd /Users/ken/cc/abc-mmm`
2. Read `UPDATING_INPUTS.md` (rules, per-tab schemas, incident log).
3. Inspect the new folder: list files, open each xlsx, check date ranges and row-level sanity.
   Compare against the expected five files (Count of store, Lighting Sale Days, Store Event Data,
   Emails, Sales by Day). Anything unexpected: ask Ken before loading it.
4. `python3 append_inputs_to_gsheet.py "<folder name>" --dry-run` and review the plan.
5. Run it live. The script appends, repairs known blank-row cases, and runs a verification pass.
6. Report to Ken as a small table: tab, rows appended, data-now-through date. Flag anything odd.
7. Add a row to the History table in `UPDATING_INPUTS.md` (and the Incident Log if something new
   bit you). Keep the runbook and script in sync with reality - the point of these docs is that
   each successor session is smarter than the last.

## Environment you need (verify before starting)

- This Mac's filesystem: repo at `/Users/ken/cc/abc-mmm`, inputs in its `inputs/` subfolder.
  If you are a cloud session without access to this machine, stop and tell Ken - the task
  needs local files and the local service-account key.
- Sheet: `ABC MMM Inputs`, ID `1CeHZVQrONTRGb2_h4mmBYefX96Of4h8Ul1C5yx0Tb7I`, owner
  ken@donutanalytics.com.
- Auth: service account `jelly-336@donut-426.iam.gserviceaccount.com`, key file
  `~/.config/gcloud/jelly-bq-sa.json`, already granted Editor on the sheet. A 403 on write
  means that grant was lost - ask Ken to re-share, do not work around it.
- Python: system python3 (3.9) with `gspread` + `google-auth` installed `--user`. openpyxl
  is present. Ignore the noisy EOL/LibreSSL warnings on stderr.

## Non-negotiables (the short version - runbook has the full list)

- **Append-only.** Never rewrite or delete existing rows except the specific in-place repairs
  the script performs automatically (trailing-blank backfill, all reconciled against source).
- **BigQuery reads this sheet live** (external tables in `donut-426.abc` feeding the Meridian
  MMM). A bad paste corrupts model inputs silently. Numeric columns take numbers or blank,
  never `'-'` or `'N/A'` strings.
- **Validate the source file's row-level semantics before trusting it.** Headers lie. The June
  2026 Emails.xlsx had a clean header but its new rows were missing five columns of data.
  Matching the tab to a malformed source verifies nothing.
- **Only eight tabs are yours**: control_storecount, control_lightning, control_celebs,
  control_email, rev_store, rev_ecom, rev_app, rev_vault. Every other tab (mmm, explore_*,
  control_vaultdrops, control_gtrends, control_promosandmail, rev_all, aj) is derived,
  Ken-maintained, or fed by another pipeline. Never write to them.
- **Ken hand-edits the sheet between runs** (he has deleted rows the script added and added
  rows the script would have). Recompute all state from the live sheet every run; the script
  does this, so prefer running it over ad-hoc code.
- **Applejack files** (e.g. `Applejack Daily Sales 2026.xlsx`) may appear in input folders.
  Standing instruction from Ken (June 2026): ignore them. The `aj` tab is not yours, and it
  has a pivot parked in columns F:G that a blind append would smash.

## Working with Ken (conventions that matter to him)

- No em-dashes in anything you write for him; use hyphens or restructure.
- He does not use git here. Deliverables and doc updates go in the working folder as files;
  do not commit, and do not ask him to.
- When something in a source file looks wrong, show him the evidence (actual rows, actual
  cells) and ask - he knows this data cold and catches things fast. When he reports a problem
  with your work ("column U is wrong"), take it literally and go look at the exact cells he
  names; he is usually right even when your verification said otherwise.
- Report outcomes as compact tables with a one-line note per anomaly. He reads fast.

## If the script aborts or the files change shape

The script fails loudly on schema surprises (column-count changes, unmapped shifted rows)
instead of pasting garbage. When that happens: inspect the file cell-by-cell, figure out the
new shape, fix the script AND document the new case in `UPDATING_INPUTS.md` (Incident Log +
relevant tab section), then re-run. That loop - fail loudly, fix, document - is how these docs
got good. Keep it going.
