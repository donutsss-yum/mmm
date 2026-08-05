# inputs/ — monthly data drop folder

Drop each month's export files here as a subfolder, e.g. `July 2026 Inputs/`, then tell
a Claude session "new files for the mix model" (or run the ingest yourself — see
`docs/INGEST.md` for the full runbook: ingest → roll window → run → report).

Expected files per month (names tolerate ` (2)`-style download suffixes):
`Count of store*.xlsx`, `Lighting Sale Days*.xlsx`, `Store Event Data*.xlsx`,
`Emails*.xlsx`, `Sales by Day*.xlsx`. Applejack files are ignored by standing
instruction.

Ingested folders are committed to git as the provenance trail of what data entered the
model when. Historical drops from the pre-git era (March–June 2026) live in
`legacy/abc-mmm/inputs/`.
