"""Decode the new 2022/2023 ABC Promotions workbooks and append them to the
control_promosandmail tab (append-only). Reuses decode_promotions.py logic.

Cell encoding is chosen to keep the BQ external-table column TYPES stable:
  - DATE cols (start/end)  -> ISO 'YYYY-MM-DD' (USER_ENTERED => real date)
  - numeric BQ cols        -> number, or '' when missing (NEVER '-')
  - string BQ money cols   -> number, '-' for 0, '' when missing
                              (matches the existing 164 rows' convention)
  - AF Redemptions         -> per-row formula '=AC{n}+Q{n}' (matches sheet)
Dry-run unless --commit is passed.
"""
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

import decode_promotions as dp  # noqa: E402

INPUTS = "/Users/ken/cc/abc-mmm/mailers-decoding/_inputs"
ALL_FILES = {
    2022: f"{INPUTS}/ABC Promotions 2022.xlsx",
    2023: f"{INPUTS}/ABC Promotions 2023.xlsx",
    2024: f"{INPUTS}/ABC Promotions 2024.xlsx",
    2025: f"{INPUTS}/ABC Promotions 2025.xlsx",
    2026: f"{INPUTS}/ABC Promotions 2026.xlsx",
}
NEW_YEARS = {2022, 2023}

SHEET_ID = "1CeHZVQrONTRGb2_h4mmBYefX96Of4h8Ul1C5yx0Tb7I"
SA_PATH = "/Users/ken/.config/gcloud/jelly-bq-sa.json"
TAB = "control_promosandmail"

# BQ external-table types observed on control_promosandmail. Anything STRING
# can safely carry the '-'-for-zero convention; numeric must never get '-'.
NUMERIC_BQ = {
    "year", "duration_days", "discount_value", "min_spend",
    "num_orders", "transactions", "gross_profit_margin", "total_discount",
}
DATE_BQ = {"start_date", "end_date"}
# STRING-in-BQ money columns where existing rows render 0 as '-'
DASH_COLS = {
    "full_retail_value", "gross_rev", "markdown_discount",
    "total_promotional_discount", "promo_discount_this_promo",
    "avg_full_retail_value", "avg_retail_value_w_sale",
    "avg_retail_value_w_sale_promo", "promo_cost_per_order_w_sale",
    "promo_cost_per_order_w_promo", "aov", "promo_sales_trans_total",
}


def decode_all():
    cat_map = dp.build_category_map(ALL_FILES.values())
    recs = []
    for yr, fname in ALL_FILES.items():
        xl = pd.ExcelFile(fname)
        for sheet in xl.sheet_names:
            if sheet == "Summary":
                continue
            df = pd.read_excel(fname, sheet_name=sheet, header=None)
            rs = dp.block_records(df, yr, f"ABC Promotions {yr}")
            for r in rs:
                r["category"] = dp.infer_category(
                    r.get("promotion_name"), r.get("description_raw"), cat_map
                )
            recs.extend(rs)
    df = pd.DataFrame(recs).dropna(subset=["promotion_name"]).reset_index(drop=True)
    df = df.drop_duplicates(subset=dp.DEDUP_KEY, keep="first").reset_index(drop=True)
    for col in dp.COLUMN_ORDER:
        if col not in df:
            df[col] = pd.NA
    df = df[dp.COLUMN_ORDER]
    return dp.coerce_types(df)


def cell(col, val):
    """One cell value, encoded to preserve the BQ column type."""
    try:
        isna = bool(pd.isna(val))
    except (TypeError, ValueError):
        isna = False
    if col in DATE_BQ:
        if isna:
            return ""
        return pd.Timestamp(val).strftime("%Y-%m-%d")
    if col in dp.STRING_FIELDS:
        return "" if isna else dp.norm(val)
    if isna:
        return ""
    num = float(val)
    if col in NUMERIC_BQ:
        return int(round(num)) if num == int(num) else num
    if col in DASH_COLS:
        return "-" if num == 0 else num
    return int(num) if num == int(num) else num  # remaining string money cols


def main():
    commit = "--commit" in sys.argv
    full = decode_all()

    # regression guard: 2024-2026 + Mailers logic unchanged (expect 164 baseline
    # minus Mailers which live in Mailers.xlsx, so the 3 yearly files only)
    base = full[full.year.isin([2024, 2025, 2026])]
    print(f"2024-2026 decoded rows: {len(base)} (sanity: was 151 yearly + 13 mailer)")

    new = full[full.year.isin(NEW_YEARS)].reset_index(drop=True)
    print(f"\nNew 2022/2023 rows to append: {len(new)}")
    print(new.groupby(["year", "channel"]).size().to_string())
    sd = pd.to_datetime(new.start_date, errors="coerce")
    print("date span:", sd.min(), "->", pd.to_datetime(new.end_date, errors="coerce").max())
    print("rows w/ num_orders:", int(new.num_orders.notna().sum()),
          "| w/ transactions:", int(new.transactions.notna().sum()),
          "| no dates:", int(new.start_date.isna().sum()))

    rows = [[cell(c, r[c]) for c in dp.COLUMN_ORDER] for _, r in new.iterrows()]
    print("\nsample encoded rows:")
    for rr in rows[:3]:
        print(" ", rr)

    if not commit:
        print("\nDRY RUN. Re-run with --commit to write to the sheet.")
        return

    import gspread
    from google.oauth2.service_account import Credentials

    sc = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
    sh = gspread.authorize(
        Credentials.from_service_account_file(SA_PATH, scopes=sc)
    ).open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB)
    existing = ws.get_all_values()
    header = existing[0]
    data_rows = len(existing) - 1
    # pre-flight: protect the shared sheet — abort on anything unexpected
    assert header[:len(dp.COLUMN_ORDER)] == dp.COLUMN_ORDER, "header drift!"
    assert header[31] == "Redemptions", f"col AF != Redemptions: {header[31]!r}"
    assert data_rows == 164, f"expected 164 existing data rows, found {data_rows}"
    start_row = len(existing) + 1
    for i, rr in enumerate(rows):
        rr.append(f"=AC{start_row + i}+Q{start_row + i}")  # column AF formula
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"\nAppended {len(rows)} rows starting at sheet row {start_row}. "
          f"New total data rows: {data_rows + len(rows)}.")


if __name__ == "__main__":
    main()
