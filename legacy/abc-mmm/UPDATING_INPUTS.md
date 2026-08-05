# Monthly MMM Input Update - Runbook

**What this is:** the operational guide for pulling a new month of input files into the **ABC MMM Inputs**
Google Sheet. Ken drops a folder like `inputs/June 2026 Inputs/` and says "bring them into the gSheet."
BigQuery reads the sheet live (external tables in `donut-426.abc`), which feeds the Meridian MMM
(`mmmv10.py`), so a bad paste silently corrupts the model inputs. Read this whole doc before touching
the sheet. It exists because every one of these rules was learned the hard way (see Incident Log).

- Sheet: `ABC MMM Inputs` - ID `1CeHZVQrONTRGb2_h4mmBYefX96Of4h8Ul1C5yx0Tb7I` (owner ken@donutanalytics.com)
- Script: `append_inputs_to_gsheet.py` (this folder) - run it, don't hand-roll new code
- Auth: service account `jelly-336@donut-426.iam.gserviceaccount.com`, key at
  `~/.config/gcloud/jelly-bq-sa.json`, granted **Editor** on the sheet (2026-04-20).
  Libraries: `gspread` + `google-auth`, installed `--user` under system python3 (3.9).

## How to run

```bash
cd /Users/ken/cc/abc-mmm
python3 append_inputs_to_gsheet.py "June 2026 Inputs" --dry-run   # inspect the plan first
python3 append_inputs_to_gsheet.py "June 2026 Inputs"             # then write + auto-verify
```

The folder argument is the subfolder of `inputs/`. Folder naming is inconsistent
("March 2026 inputs" vs "June 2026 Inputs") and filenames may carry browser-download
suffixes like `Emails (3).xlsx` - the script glob-matches both.

## Golden rules

1. **Append-only.** Ken chose this explicitly (over full-overwrite or shape-matching rewrites).
   Existing rows are never modified except to repair a defect, and repairs get confirmed by
   reconciliation against the source file.
2. **Validate the source file's semantics BEFORE pasting.** Do not trust the header row. The
   June 2026 Emails.xlsx had a correct header but its *new* rows were missing five columns of
   data (see Incident Log #1). Check that rate columns hold rates (0-1 floats), text columns
   hold text, at the actual row level.
3. **Verifying tab == source proves nothing if the source is malformed.** GIGO. Semantic checks
   (types, ranges, weekday-vs-date agreement) are the real safety net.
4. **Numeric columns get numbers or blank, never `'-'` or `'N/A'`.** BQ external tables type
   these columns; a stray string breaks the typed read. The `-` seen in Vault exports means
   zero-ish/no-data and must become blank.
5. **Dates as `M/D/YYYY` strings with USER_ENTERED**, never raw serial numbers. Some tabs lack
   date formatting on new rows, so a serial pastes as `46119` and stays that way.
6. **Sort batches by real date value, not date string.** `'5/26/2026' < '5/8/2026'` lexically.
7. **Only touch the eight input tabs listed below.** Everything else (`mmm`, `explore_*`,
   `control_vaultdrops`, `control_gtrends`, `control_promosandmail`, `rev_all`, `aj`) is either
   derived, maintained by Ken, or fed by another pipeline.
8. **Ken edits the sheet directly between runs.** Never assume the tab state matches where the
   last run left it. Recompute cutoffs/keys from the live tab every time.

## File -> tab map

| Input file (glob) | Sheet in xlsx | Tab | Dedupe key |
|---|---|---|---|
| `Count of store*.xlsx` | Sheet1 | `control_storecount` | date cutoff |
| `Lighting Sale Days*.xlsx` | Sheet1 | `control_lightning` | date cutoff |
| `Store Event Data*.xlsx` | Sheet1 | `control_celebs` | **full-row multiset** |
| `Emails*.xlsx` | Sheet1 | `control_email` | **Campaign ID** |
| `Sales by Day*.xlsx` | Store Sales | `rev_store` | date cutoff |
| `Sales by Day*.xlsx` | ABCFWS sales | `rev_ecom` | date cutoff |
| `Sales by Day*.xlsx` | App Sales | `rev_app` | date cutoff |
| `Sales by Day*.xlsx` | Vault Sales | `rev_vault` | date cutoff |

Any other file in the folder gets skipped with a notice. In June 2026 an
`Applejack Daily Sales 2026.xlsx` appeared (Applejack = different client, feeds the `aj` tab
as a market covariate); **Ken said ignore it**. The `aj` tab also has a pivot parked in
columns F:G, so never blind-append there. Ask before ever loading Applejack data.

### Per-tab specifics

**control_storecount** - `Date | Stores | StorespWeek`. Source has year-rollup rows
(`'2024', 45618`) mixed in; keep only rows whose col A is a real datetime. Column C is a live
formula, continue it on every new row: `=B{row}/7`. Trailing dates with blank counts are
normal (export ends before data does) and stay blank.

**control_lightning** - `Date | LS | LS_Days`. Source cols: Day, Day-of-week, sale-flag
("Yes" or empty). LS = the flag verbatim, LS_Days = the weekday-weighted IFS formula
(copy it from the script, it maps Sun..Sat to 10/11/12/13/14/21/20).

**control_celebs** - `Date | Store # | Event Type | Brand | Celebrity` (source has a leading
Pcode column - drop it). **A date cutoff is NOT a valid dedupe here**: events get added
retroactively, Ken hand-edits this tab, and one physical event with N product Pcodes is
intentionally N duplicate rows. Reconcile as a full-row multiset diff (tab vs source),
insert missing rows adjacent to their date group. Report tab-only rows as warnings, never
delete them.

**control_email** - 33 columns, A..AG: Budget, Date, Campaign ID, Campaign Name, Send Date,
Send Time, Total Recipients, Open Rate, Click Rate, Unsub Rate, Bounce Rate, Spam Rate,
Total Opens, Total Clicks, Total Unsubs, Bounces, Spam Complaints, Started Checkout,
Started Checkout Rate, Placed Order, Placed Order Rate, Fulfilled Order, Fulfilled Value,
KL Custom Conversion, Tags, Subject, Preview Text, List, Excluded List, Day of Week,
Campaign Channel, Email List, Email Type. (Header row labels stop at AE; AF/AG are unlabeled
but hold Email List / Email Type.)
- Dedupe by **Campaign ID against the whole tab** (send-date cutoffs miss late-added campaigns).
- **Shifted-row detection is mandatory** (Incident #1): a row is shifted iff its Subject slot
  (index 25) reads `'Email'`. Shifted rows lack the five rate columns; remap indices
  7-27 -> 12-32 and leave rates (H-L) blank. The rates are NOT derivable from counts
  (Klaviyo rates use unique opens/clicks, which aren't exported).
- Email Type `#N/A` is literal text; USER_ENTERED turns it into a real error value, so those
  cells get rewritten RAW.
- Send Time: write as `h:mm AM/PM` text and set that number format on the new range
  (matches the tab's historical display).
- Day of Week derives from Send Date; Campaign Channel is `'Email'` on 100% of history.

**rev_store** - `Date | Sales | Trans | Units`. Source "Store Sales" sheet: junk title rows
(real header is row 3), one row per store per day (15k+ rows), plus a `Total` row - skip
non-datetime col A. Aggregate SUM by date over cols 2 (Sales), 6 (Trans), 14 (Units).
Spot-check one aggregated day against the source after writing.

**rev_ecom / rev_app / rev_vault** - `Date | Full List Price | Orders | Units`. Source has 6
cols; keep Date + cols 3/4/5, drop Gross/Net revenue (cols 1/2). `'-'` -> blank. Vault is
mostly blank with occasional real drops (e.g. 4/8/2026 = $269k) - blanks are correct, don't
"fix" them, and real values in a previously-blank stretch are legitimate.

## Data facts that look like bugs but aren't

- **4/5/2026 = $0 store sales and blank store count**: Easter Sunday, ABC stores closed.
- **Fulfilled Order count > Placed Order count** on email rows: normal in this Klaviyo export.
- **Trailing blank metric rows** at the newest dates: the export ends before the data does.
  The script no longer appends them (Ken deletes them - he removed the blank 6/30 storecount
  row after the June run), and it repairs any previously-appended trailing blank row in place
  once a later file carries real values for that date. Interior blanks (Easter) stay blank.
- **control_email rows 835-873 have blank rate columns (H-L)**: permanent gap from Incident #1;
  the source never contained those values.

## Incident log (why the rules exist)

1. **June 2026 - Emails.xlsx shifted rows.** The file's 39 new campaign rows were missing the
   five rate columns; every later value sat 5 columns left (Subject landed in U). Old rows in
   the same file were fine, so whole-file column scans passed. First paste copied the shift
   into the tab; the "verification" compared tab to the same shifted source and passed (GIGO).
   Ken caught it by eye (string in U at row 835). Fix: remap in place, rates left blank.
   Detection is now automated (Subject-slot == 'Email').
2. **June 2026 - celebs 0-new-rows false negative.** Date-cutoff dedupe reported nothing to add
   even though the file had 12 new events: Ken had hand-updated the tab, but his version missed
   one duplicate row each on two multi-Pcode events. Full-row multiset reconcile found them.
3. **April 2026 - raw serials displayed.** Appending serial numbers left `46119`-style values
   showing in `control_lightning`/`control_celebs` (no date format on new rows). Rule 5.
4. **May 2026 - string-sorted dates.** The email batch appended in lexical date order
   (5/26 before 5/8). Harmless but confusing. Rule 6.
5. **March 2026 - SA lacked edit rights.** First write attempt 403'd; sheet was
   anyone-with-link **commenter**. Ken added the SA as Editor; if a 403 recurs, that grant
   is the first thing to check.
6. **July 2026 - trailing blank row deleted by Ken.** The June run appended a 6/30 storecount
   row with a blank count (source had the date but no value yet); Ken deleted it. A date-cutoff
   dedupe would then have re-appended it blank forever, and worse, blank rows that DO stay in
   the tab (rev_ecom/app/vault 6/30) can never receive their real values via append. The script
   now truncates trailing all-blank rows before appending and repairs previously-appended
   trailing blanks in place when a later file has the values.

## History

| Round | Data through | Notes |
|---|---|---|
| March 2026 (base `inputs/*.xlsx`) | ~4/6-4/9/2026 | First automated append; SA granted Editor |
| April 2026 | ~5/2-5/3/2026 | Store Event Data unchanged that month |
| May 2026 | ~5/30-5/31/2026 | No Store Event Data file in folder |
| June 2026 | 6/29-6/30/2026 | Applejack file skipped per Ken; email shift incident + fix; celebs reconciled (112 rows incl header) |

After each future run: append a row here, and update the Incident Log if anything new bit you.
