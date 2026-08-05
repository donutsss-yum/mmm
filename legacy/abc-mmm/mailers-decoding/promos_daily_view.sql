-- Daily-spread view of ABC promotions, modeled on the gSheet_amex pattern.
-- Each promo's Redemptions value is divided evenly across every active day
-- (start_date .. end_date inclusive) and emitted one row per day.
--
-- Source: abc.gSheet_promos (named columns, real DATE/INTEGER types).
-- Redemptions = num_orders + transactions (the AC+Q column added in the CSV;
-- verified to match that sum exactly on every row).
-- Rows with no dates (4) drop out via the date guards.

CREATE OR REPLACE VIEW `abc.promos_daily` AS
SELECT
  daily_date                                                    AS Date,
  'ABC Promo'                                                    AS Platform,
  p.channel                                                      AS Placement,
  p.category                                                     AS AccountName,
  p.promotion_name                                               AS CampaignName,
  p.Redemptions / (DATE_DIFF(p.end_date, p.start_date, DAY) + 1) AS Redemptions
FROM `abc.gSheet_promos` AS p
CROSS JOIN UNNEST(
  GENERATE_DATE_ARRAY(p.start_date, p.end_date, INTERVAL 1 DAY)
) AS daily_date
WHERE p.start_date  IS NOT NULL
  AND p.end_date    IS NOT NULL
  AND p.Redemptions IS NOT NULL
  AND p.end_date >= p.start_date;
