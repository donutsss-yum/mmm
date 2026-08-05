CREATE OR REPLACE VIEW `donut-426.abc.promos_daily` AS
SELECT
  daily_date AS Date,
  p.channel AS Channel,
  p.category AS Category,
  p.promotion_name AS CampaignName,
  p.Redemptions / (DATE_DIFF(p.end_date, p.start_date, DAY) + 1) AS Redemptions_Total,

  CASE
    WHEN REGEXP_CONTAINS(REGEXP_REPLACE(LOWER(p.category), r'[^a-z]', ''), r'birthday|signup')
      THEN p.Redemptions / (DATE_DIFF(p.end_date, p.start_date, DAY) + 1)
    ELSE 0
  END AS Redemptions_Birthday_Signup,

  CASE
    WHEN REGEXP_CONTAINS(REGEXP_REPLACE(LOWER(p.category), r'[^a-z]', ''), r'birthday|signup')
      THEN 0
    ELSE p.Redemptions / (DATE_DIFF(p.end_date, p.start_date, DAY) + 1)
  END AS Redemptions_Other

FROM
  (
    SELECT promotion_name, category, channel, start_date, end_date, Redemptions
    FROM `donut-426.abc.gSheet_promos`
  ) AS p
CROSS JOIN
  UNNEST(GENERATE_DATE_ARRAY(p.start_date, p.end_date, INTERVAL 1 DAY))
    AS daily_date
WHERE p.Redemptions IS NOT NULL AND p.end_date >= p.start_date;
