-- Query: total freight cost by carrier in August 2026
WITH df1 AS (
  SELECT
    dispatch_date,
    carrier,
    freight_cost_usd
  FROM ycw_dispatch
), df2 AS (
  SELECT
    *
  FROM df1
  WHERE
    dispatch_date >= '2026-08-01'
), df3 AS (
  SELECT
    *
  FROM df2
  WHERE
    dispatch_date < '2026-09-01'
), df4 AS (
  SELECT
    carrier,
    SUM(freight_cost_usd) AS sum_freight_cost_usd
  FROM df3
  GROUP BY
    carrier
)
SELECT
  carrier,
  sum_freight_cost_usd
FROM df4
