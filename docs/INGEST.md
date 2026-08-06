# Monthly data refresh (ingest → roll forward → run → report)

**What this is:** the end-to-end runbook for getting a new month of data into the model
and fresh results out. The ingest half is inherited from four battle-tested rounds
(March–June 2026) documented in `legacy/abc-mmm/UPDATING_INPUTS.md` +
`HANDOFF_MONTHLY_UPDATES.md` (frozen archive — the living version is THIS file).
The roll-forward/run half is new with the git-native pipeline.

**The trigger:** Ken drops a folder like `inputs/July 2026 Inputs/` into the repo and
says "new files for the mix model." An agent session takes it from there.

## The drop

`inputs/<Month Year> Inputs/` at the repo root, containing up to five xlsx files
(names may carry browser-download suffixes like `Emails (3).xlsx` — the script
glob-matches):

| File | Feeds sheet tab(s) | Notes |
|---|---|---|
| `Count of store*.xlsx` | `control_storecount` | |
| `Lighting Sale Days*.xlsx` | `control_lightning` | |
| `Store Event Data*.xlsx` | `control_celebs` | sometimes absent — fine |
| `Emails*.xlsx` | `control_email` | Klaviyo export, 33 cols |
| `Sales by Day*.xlsx` | `rev_store`, `rev_ecom`, `rev_app`, `rev_vault` | 4 sheets inside |

**Standing instruction (Ken, June 2026): Applejack files are IGNORED** (different
client, feeds the `aj` tab via another path; that tab has a pivot parked in F:G that a
blind append would smash). Any other unexpected file: ask Ken before loading.

The input folder gets **committed to git after a successful ingest** — that's the
provenance trail for what data entered the model when.

## Step 1 — Ingest into the Google Sheet

```bash
.venv/bin/python scripts/append_inputs_to_gsheet.py "July 2026 Inputs" --dry-run  # review plan
.venv/bin/python scripts/append_inputs_to_gsheet.py "July 2026 Inputs"            # write + verify
```

- Sheet: `ABC MMM Inputs`, ID `1CeHZVQrONTRGb2_h4mmBYefX96Of4h8Ul1C5yx0Tb7I`.
  **BigQuery reads it live** (Sheets-backed external tables in `donut-426.abc` feed the
  `abc.mmm` view) — a bad paste silently corrupts model inputs.
- Auth: service-account key `~/.config/gcloud/jelly-bq-sa.json` on Ken's Mac
  (`jelly-336@donut-426`, Editor on the sheet); ADC fallback elsewhere. A 403 = the
  Editor grant was lost — ask Ken to re-share, never work around it.
- The script appends, repairs known trailing-blank cases, and runs a semantic
  verification pass. It **fails loudly on schema surprises** — when it aborts, inspect
  the file cell-by-cell, fix the script, document the new case here, re-run.

### Golden rules (each learned the hard way — incident log below)

1. **Append-only.** Never rewrite/delete existing rows beyond the script's reconciled
   trailing-blank repairs.
2. **Only eight tabs are writable**: `control_storecount`, `control_lightning`,
   `control_celebs`, `control_email`, `rev_store`, `rev_ecom`, `rev_app`, `rev_vault`.
   Everything else (`mmm`, `explore_*`, `control_vaultdrops`, `control_gtrends`,
   `control_promosandmail`, `rev_all`, `aj`) is derived, Ken-maintained, or fed by
   another pipeline.
3. **Validate source-row semantics before trusting a file** — headers lie (June 2026:
   clean header, new rows missing five columns).
4. Numeric columns take **numbers or blank**, never `'-'`/`'N/A'` strings (BQ types them).
5. Dates as `M/D/YYYY` strings with USER_ENTERED, never raw serials.
6. Sort batches by real date value, not date string.
7. **Ken hand-edits the sheet between runs** — recompute all state from the live sheet
   every run (the script does).
8. Trailing blank-metric rows are truncated on append and repaired in place later.

### Per-tab subtleties (full detail: `legacy/abc-mmm/UPDATING_INPUTS.md`)

- `control_storecount`: skip year-rollup rows; col C is a live `=B{n}/7` formula.
- `control_lightning`: LS_Days is a weekday-weighted IFS formula (in the script).
- `control_celebs`: **full-row multiset reconcile, not date cutoff** (retroactive
  events; N Pcodes = N intentional duplicate rows). Tab-only rows are warnings, never
  deletions.
- `control_email`: dedupe by Campaign ID; **shifted-row detection is mandatory**
  (Subject slot reading `'Email'` = the shift signature); rates on shifted rows stay
  blank forever (not derivable); `#N/A` Email Type written RAW.
- `rev_store`: aggregate per-store-per-day rows to daily sums; real header is row 3.
- `rev_ecom/app/vault`: keep Date + List Price/Orders/Units; `'-'` → blank; Vault's
  long blank stretches are correct.

### Data facts that look like bugs but aren't

Easter Sunday $0 store sales (stores closed); Fulfilled > Placed on email rows;
email rows 835–873 have permanently blank rate columns (Incident #1); trailing
export-lag blanks.

## Step 2 — Roll the model window forward

The sheet feeds BQ live, so data flows automatically — but **which weeks enter the
model** is gated by `Model_Dates` in `sql/abc_mmm_view.sql`:

1. Edit the `CASE WHEN Time BETWEEN DATE '2023-01-01' AND DATE '<end>'` line — set
   `<end>` to the last day of the last **complete** week of new data. Ken sometimes
   also moves the start date up to keep ~156 weeks (3y) — ask him or leave start alone.
2. Apply: `bq query --use_legacy_sql=false "$(cat sql/abc_mmm_view.sql)"` (or paste
   into the BQ console). Commit the SQL change.
3. Roll the **report window** in `steps/02_diagnostics.py` (`start_date, end_date`) —
   must span 52/53 week-start days ending at the new data edge. Commit.

## Step 3 — Run and report

```bash
caffeinate -i .venv/bin/python scripts/run_local.py        # 00 01 save 02 03 04 (~6 min)
.venv/bin/python scripts/run_local.py 05                   # only if Ken wants the dashboard refreshed
```

Check: `PREFLIGHT OK`; data shape grew by ~4-5 weeks; all r_hat = 1.0; new HTML/CSVs
in Drive. Report to Ken as a compact table: tab, rows appended, data-now-through date,
plus fit sanity (r_hat, shape) and links/paths to outputs. One line per anomaly.

## Step 4 — Log and commit

- Add a row to the History table below (+ Incident log if something new bit you).
- `docs/SESSION_LOG.md` entry; commit: input folder + SQL + report window + docs.

## Incident log (inherited 2026-08; new incidents go here)

1. **Jun 2026 — Emails.xlsx shifted rows**: new rows missing five rate columns; paste
   copied the shift; tab-vs-source "verification" passed (GIGO). Ken caught it by eye.
   → automated shift detection + remap; rates permanently blank on those rows.
2. **Jun 2026 — celebs false negative**: date-cutoff dedupe missed 12 retroactive
   events → full-row multiset reconcile.
3. **Apr 2026 — raw date serials** displayed (`46119`) → M/D/YYYY strings rule.
4. **May 2026 — lexical date sort** (5/26 before 5/8) → sort by serial.
5. **Mar 2026 — SA lacked Editor** → 403 means re-share, nothing else.
6. **Jul 2026 — trailing blank rows**: Ken deletes them; blanks already appended can
   never get values via append → truncate-on-append + in-place repair.

## History

| Round | Data through | Notes |
|---|---|---|
| Mar 2026 | ~4/6–4/9/2026 | First automated append; SA granted Editor |
| Apr 2026 | ~5/2–5/3/2026 | Store Event Data unchanged |
| May 2026 | ~5/30–5/31/2026 | No Store Event Data file |
| Jun 2026 | 6/29–6/30/2026 | Applejack skipped; email shift incident + fix; celebs reconciled |
| — | — | *(migrated to git-native pipeline 2026-08-05; next round starts here)* |
| Jul 2026 | 8/1–8/3 (ecom 7/6, vault 7/31) | Folder `inputs/reupdateddatathrough81`. Dry run reviewed+approved 2026-08-05 (cloud session); live append applied same day per that plan: storecount 33, lightning 34, celebs 0 (clean reconcile), email 38, rev_store 33, rev_ecom repair 6/30 + 6, rev_app 34, rev_vault repair 6/30 ($258k) + 31. The finishing session (2026-08-05 evening) found the append already in the sheet — its live run no-op'd on all 8 tabs and ran verification: **CLEAN**. Spot-checked: vault 6/30 = $258,419, ecom 6/30 repaired, lightning tail carries the script's LS_Days formula (script provenance confirmed). **Refresh stopped after ingest — window NOT rolled** (`Model_Dates` still ends 2026-06-27). Open flags: (1) rev_ecom source blank after 7/6 — export lag? model window must not pass 7/6 until resolved; (2) `Vault Day.xlsx` skipped as unrecognized — awaiting Ken's ruling; (3) Google Trends not yet updated; (4) cosmetic: email dry-run "span" prints Budget not dates. |

## The media side (automatic — no ingest step)

`donut-426.abc.media` (impressions/spend/clicks per platform) is fed by **Power My
Analytics**, a connector service that delivers into BigQuery **daily, automatically**
(confirmed by Ken, 2026-08-05). Nothing to load manually. During a refresh, just
verify PMA is caught up to the new window before fitting:

```bash
.venv/bin/python -c "import pandas_gbq; print(pandas_gbq.read_gbq(\"SELECT MAX(time) AS last_media_week FROM abc.mmm WHERE All_spend > 0\", project_id='donut-426'))"
```

`last_media_week` should be at or past the intended `Model_Dates` end-date. If media
lags the revenue data, either wait for PMA to catch up or set the window end to the
last week BOTH sides cover — never fit weeks where revenue exists but media reads as
zero (the model would read that as "sales without ads" and misattribute to baseline).
If media looks stale by more than a couple of days, the PMA connector itself is the
thing to check — that's Ken's side.
