-- ============================================================================
-- donut-426.abc.mmm  —  the weekly "blender" view the MMM pipeline reads.
--
-- THIS FILE IS THE VERSIONED SOURCE OF TRUTH for the view definition (added to
-- git 2026-08-05; previously it lived only inside BigQuery). Workflow for
-- changing the view: edit HERE first, commit, then apply to BigQuery by
-- pasting this whole file into the BQ console (it is a complete
-- CREATE OR REPLACE VIEW statement), or:
--     bq query --use_legacy_sql=false < sql/abc_mmm_view.sql
--
-- Structure: a UNION ALL of 9 source blocks (media, revenue, vault drops,
-- gtrends, email, lightning, storecount, celebs, promos), each filling its own
-- columns and NULLs elsewhere, then a final weekly GROUP BY. UNION ALL matches
-- columns BY POSITION - any new column must be added at the same position in
-- ALL NINE blocks.
--
-- CHANGES 2026-08-05 (for the exp/v14-revenue-split experiment):
--   + Revenue_InStore / Revenue_Ecom / Revenue_App / Revenue_Vault pulled from
--     abc.gSheet_rev (they always existed in the daily sheet tab) and exposed
--     weekly as Conversions_Revenue_InStore / _Ecom / _App / _Vault.
--     Non-breaking: the v13 pipeline selects columns by name.
--     Sanity gate after applying: the four splits must sum to
--     Conversions_Revenue each week (see reconciliation query in
--     docs/SESSION_LOG.md 2026-08-05 entry).
-- ============================================================================
CREATE OR REPLACE VIEW `donut-426.abc.mmm` AS
WITH blender AS (
  -- Media / Ad spend part
  SELECT
    Date_Week_Start AS time,
    SUM(Impressions) AS All_Impression,
    SUM(Cost)       AS All_Spend,

    SUM(CASE WHEN Platform = 'Meta' THEN Impressions ELSE 0 END) AS Meta_Impression,
    SUM(CASE WHEN Platform = 'Meta' THEN Cost       ELSE 0 END) AS Meta_Spend,

    SUM(CASE WHEN Placement IN ('Search', 'App') THEN Impressions ELSE 0 END) AS Search_Impression,
    SUM(CASE WHEN Placement IN ('Search', 'App') THEN Cost       ELSE 0 END) AS Search_Spend,
    SUM(CASE WHEN Placement IN ('Search', 'App') THEN Clicks     ELSE 0 END) AS Search_Click,

    SUM(CASE WHEN Placement = 'PMAX' THEN Impressions ELSE 0 END) AS PMAX_Impression,
    SUM(CASE WHEN Placement = 'PMAX' THEN Cost       ELSE 0 END) AS PMAX_Spend,

    SUM(CASE WHEN Platform = 'Amex' THEN Impressions ELSE 0 END) AS Amex_Impression,
    SUM(CASE WHEN Platform = 'Amex' THEN Cost       ELSE 0 END) AS Amex_Spend,

    -- All video together
    SUM(CASE WHEN Placement = 'Video' THEN Impressions ELSE 0 END) AS Video_Impression,
    SUM(CASE WHEN Placement = 'Video' THEN Cost       ELSE 0 END) AS Video_Spend,

    -- Video broken out by partner
    SUM(CASE WHEN Platform = 'Epsilon'  AND Placement = 'Video' THEN Impressions ELSE 0 END) AS Video_Epsilon_Impression,
    SUM(CASE WHEN Platform = 'Epsilon'  AND Placement = 'Video' THEN Cost       ELSE 0 END) AS Video_Epsilon_Spend,
    SUM(CASE WHEN Platform = 'Google'   AND Placement = 'Video' THEN Impressions ELSE 0 END) AS Video_Google_Impression,
    SUM(CASE WHEN Platform = 'Google'   AND Placement = 'Video' THEN Cost       ELSE 0 END) AS Video_Google_Spend,
    SUM(CASE WHEN Platform = 'Hulu'     AND Placement = 'Video' THEN Impressions ELSE 0 END) AS Video_Hulu_Impression,
    SUM(CASE WHEN Platform = 'Hulu'     AND Placement = 'Video' THEN Cost       ELSE 0 END) AS Video_Hulu_Spend,
    SUM(CASE WHEN Platform = 'MNTN'     AND Placement = 'Video' THEN Impressions ELSE 0 END) AS Video_MNTN_Impression,
    SUM(CASE WHEN Platform = 'MNTN'     AND Placement = 'Video' THEN Cost       ELSE 0 END) AS Video_MNTN_Spend,
    SUM(CASE WHEN Platform = 'Paramount' AND Placement = 'Video' THEN Impressions ELSE 0 END) AS Video_Paramount_Impression,
    SUM(CASE WHEN Platform = 'Paramount' AND Placement = 'Video' THEN Cost       ELSE 0 END) AS Video_Paramount_Spend,
    SUM(CASE WHEN Platform = 'Peacock'  AND Placement = 'Video' THEN Impressions ELSE 0 END) AS Video_Peacock_Impression,
    SUM(CASE WHEN Platform = 'Peacock'  AND Placement = 'Video' THEN Cost       ELSE 0 END) AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    NULL AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    0    AS Email_Sends,
    0    AS Email_Spend,
    0    AS LightningSales,
    0    AS StoreCount,
    0 as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `donut-426.abc.media`
  GROUP BY all

  UNION ALL

  -- Revenue
  SELECT
    DATE_TRUNC(Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    ROUND(SUM(Rev_All), 2)         AS Revenue,
    SUM(CAST(Trans_All AS INT64))  AS Transactions,
    SUM(CAST(Units_All  AS INT64)) AS Units,
    -- v14 experiment: weekly revenue split by channel-of-sale (columns have
    -- always existed in the daily sheet tab behind abc.gSheet_rev)
    ROUND(SUM(Rev_InStore), 2)     AS Revenue_InStore,
    ROUND(SUM(Rev_Ecom), 2)        AS Revenue_Ecom,
    ROUND(SUM(Rev_App), 2)         AS Revenue_App,
    ROUND(SUM(Rev_Vault), 2)       AS Revenue_Vault,
    NULL AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    0    AS Email_Sends,
    0    AS Email_Spend,
    0    AS LightningSales,
    0    AS StoreCount,
    Null as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `abc.gSheet_rev`
  GROUP BY all

  UNION ALL

  -- Vault Drops
  SELECT
    DATE_TRUNC(Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    SUM(Vault_Drops) AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    0    AS Email_Sends,
    0    AS Email_Spend,
    0    AS LightningSales,
    0    AS StoreCount,
    Null as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `abc.gSheet_control_vaultdrops`
  GROUP BY 1

  UNION ALL

  -- Google Trends
  SELECT
    DATE_TRUNC(Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    NULL AS Vault_Drops,
    SUM(Category_Interest) AS Category_Interest,
    CASE WHEN SUM(Hurricanes) > 20 THEN SUM(Hurricanes) ELSE 0 END AS Hurricanes,
    0    AS Email_Sends,
    0    AS Email_Spend,
    0.   AS LightningSales,
    0    AS StoreCount,
    Null as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `abc.gSheet_gtrends`
  GROUP BY ALL

  UNION ALL

  -- Email
  SELECT
    DATE_TRUNC(Send_Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    NULL AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    SUM(Total_Recipients) AS Email_Sends,
    SUM(budget)           AS Email_Spend,
    0 as LightningSales,
    0    AS StoreCount,
    Null as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `abc.gSheet_email`
  GROUP BY ALL

UNION ALL


  --lightning sale
  SELECT
    DATE_TRUNC(Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    NULL AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    Null as Email_Sends,
    Null as Email_Spend,
    sum (LS_Days) as LightningSales,
    0    AS StoreCount,
    Null as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `abc.gSheet_lightning`
  GROUP BY ALL

UNION ALL

--storecount
SELECT
    DATE_TRUNC(Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    NULL AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    Null as Email_Sends,
    Null as Email_Spend,
    0    AS LightningSales,
    SUM(StorespWeek) AS StoreCount,
    Null as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `abc.gSheet_storecount`
  GROUP BY ALL

Union ALL

--celebs
SELECT
    DATE_TRUNC(Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    NULL AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    Null as Email_Sends,
    Null as Email_Spend,
    0    AS LightningSales,
    Null AS StoreCount,
    Count(Distinct(date)) as Celebs,
    NULL AS Redemptions_Birthday_Signup,
    NULL AS Redemptions_Other

  FROM `abc.gSheet_celebs`
  GROUP BY ALL

UNION ALL

--promo redemptions (birthday / new sign ups vs other)
SELECT
    DATE_TRUNC(Date, WEEK(SUNDAY)) AS time,
    NULL AS All_Impressions,
    NULL AS All_Spend,
    NULL AS Meta_Impressions,
    NULL AS Meta_Spend,
    NULL AS Search_Impressions,
    NULL AS Search_Spend,
    NULL AS Search_Clicks,
    NULL AS PMAX_Impressions,
    NULL AS PMAX_Spend,
    NULL AS Amex_Impressions,
    NULL AS Amex_Spend,
    NULL AS Video_Impressions,
    NULL AS Video_Spend,

    NULL AS Video_Epsilon_Impressions,
    NULL AS Video_Epsilon_Spend,
    NULL AS Video_Google_Impressions,
    NULL AS Video_Google_Spend,
    NULL AS Video_Hulu_Impressions,
    NULL AS Video_Hulu_Spend,
    NULL AS Video_MNTN_Impressions,
    NULL AS Video_MNTN_Spend,
    NULL AS Video_Paramount_Impressions,
    NULL AS Video_Paramount_Spend,
    NULL AS Video_Peacock_Impressions,
    NULL AS Video_Peacock_Spend,

    NULL AS Revenue,
    NULL AS Transactions,
    NULL AS Units,
    NULL AS Revenue_InStore,
    NULL AS Revenue_Ecom,
    NULL AS Revenue_App,
    NULL AS Revenue_Vault,
    NULL AS Vault_Drops,
    NULL AS Category_Interest,
    NULL AS Hurricanes,
    Null as Email_Sends,
    Null as Email_Spend,
    0    AS LightningSales,
    Null AS StoreCount,
    Null as Celebs,
    SUM(Redemptions_Birthday_Signup) AS Redemptions_Birthday_Signup,
    SUM(Redemptions_Other)           AS Redemptions_Other

  FROM `abc.promos_daily`
  GROUP BY ALL


)

SELECT
  Time as time,
  CASE
    WHEN Time BETWEEN DATE '2023-01-01' AND DATE '2026-06-27' -- Add the last day of the last week of full data on refresh. Recently I've been moving the start time up as well to keep it to 156 weeks total (3y) but could go longer than 3y if needed
    THEN 'In Model'
    ELSE 'Out of Model'
  END AS Model_Dates,

  'FL' AS geo,
  100 AS population,

  CAST(SUM(All_Impression)   AS INT64) AS All_impression,
  ROUND(SUM(All_Spend + Email_Spend), 2) AS All_spend,

  CAST(SUM(Meta_Impression)  AS INT64) AS Meta_impression,
  ROUND(SUM(Meta_Spend), 2)             AS Meta_spend,

  CAST(SUM(Search_Impression) AS INT64) AS Search_impression,
  ROUND(SUM(Search_Spend), 2)            AS Search_spend,
  CAST(SUM(Search_Click)  AS INT64)     AS Search_click,

  CAST(SUM(PMAX_Impression) AS INT64)   AS PMAX_impression,
  ROUND(SUM(PMAX_Spend), 2)              AS PMAX_spend,

  CAST(SUM(Amex_Impression) AS INT64)   AS Amex_impression,
  ROUND(SUM(Amex_Spend), 2)              AS Amex_spend,

  CAST(SUM(Video_Impression) AS INT64)  AS Video_impression,
  ROUND(SUM(Video_Spend), 2)             AS Video_spend,

  CAST(SUM(Video_Epsilon_Impression)  AS INT64) AS Video_Epsilon_impression,
  ROUND(SUM(Video_Epsilon_Spend), 2)             AS Video_Epsilon_spend,
  CAST(SUM(Video_Google_Impression)   AS INT64) AS Video_Google_impression,
  ROUND(SUM(Video_Google_Spend), 2)              AS Video_Google_spend,
  CAST(SUM(Video_Hulu_Impression)     AS INT64) AS Video_Hulu_impression,
  ROUND(SUM(Video_Hulu_Spend), 2)                AS Video_Hulu_spend,
  CAST(SUM(Video_MNTN_Impression)     AS INT64) AS Video_MNTN_impression,
  ROUND(SUM(Video_MNTN_Spend), 2)                AS Video_MNTN_spend,
  CAST(SUM(Video_Paramount_Impression) AS INT64) AS Video_Paramount_impression,
  ROUND(SUM(Video_Paramount_Spend), 2)            AS Video_Paramount_spend,
  CAST(SUM(Video_Peacock_Impression)  AS INT64) AS Video_Peacock_impression,
  ROUND(SUM(Video_Peacock_Spend), 2)             AS Video_Peacock_spend,

  ROUND(SUM(Revenue), 2)                 AS Conversions_Revenue,
  SUM(Transactions)                      AS Conversions_Transactions,
  SUM(Units)                             AS Conversions_Units,

  -- v14 experiment: weekly revenue split by channel-of-sale. Must reconcile:
  -- InStore + Ecom + App + Vault = Conversions_Revenue (within rounding).
  ROUND(SUM(Revenue_InStore), 2)         AS Conversions_Revenue_InStore,
  ROUND(SUM(Revenue_Ecom), 2)            AS Conversions_Revenue_Ecom,
  ROUND(SUM(Revenue_App), 2)             AS Conversions_Revenue_App,
  ROUND(SUM(Revenue_Vault), 2)           AS Conversions_Revenue_Vault,

  SAFE_DIVIDE(SUM(Revenue), SUM(Units))        AS Conversions_Pricing,
  SAFE_DIVIDE(SUM(Units),   SUM(Transactions)) AS Conversions_BasketSize,

  SUM(Vault_Drops)       AS Vault_Drops,
  SUM(Category_Interest) AS Category_Interest,
  SUM(Hurricanes)        AS Hurricanes,
  SUM(Email_Sends)       AS Email_sends,
  ROUND(SUM(Email_Spend), 2) AS Email_spend,
  SUM(LightningSales)     AS LightningSales,
  SUM(StoreCount)         AS StoreCount,
  Sum(Celebs)             AS Celebs,
  if(Round((SUM(Redemptions_Birthday_Signup)),2) IS NULL, 0, Round((SUM(Redemptions_Birthday_Signup)),2)) AS Redemptions_Birthday_Signup,
  IF(Round((SUM(Redemptions_Other)),2)  IS NULL,          0, Round((SUM(Redemptions_Other)),2))           AS Redemptions_Other

FROM blender
GROUP BY all
ORDER BY Time
