-- Query: forecast freight cost next 2 months
WITH df1 AS (
  SELECT
    dispatch_date,
    freight_cost_usd
  FROM ycw_dispatch
), df2 AS (
  SELECT
    *,
    STRFTIME(dispatch_date, '%Y-%m') AS dispatch_date_month
  FROM df1
), df3 AS (
  SELECT
    dispatch_date_month,
    SUM(freight_cost_usd) AS sum_freight_cost_usd
  FROM df2
  GROUP BY
    dispatch_date_month
)
SELECT
  dispatch_date_month,
  sum_freight_cost_usd
FROM df3
