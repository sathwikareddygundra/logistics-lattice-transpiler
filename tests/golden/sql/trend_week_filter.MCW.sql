-- Query: weekly freight cost for DHL
WITH df1 AS (
  SELECT
    dispatch_date,
    carrier,
    freight_cost_usd
  FROM dispatch
), df2 AS (
  SELECT
    *
  FROM df1
  WHERE
    carrier = 'DHL'
), df3 AS (
  SELECT
    *,
    STRFTIME('%Y-W%W', dispatch_date) AS dispatch_date_week
  FROM df2
), df4 AS (
  SELECT
    dispatch_date_week,
    SUM(freight_cost_usd) AS sum_freight_cost_usd
  FROM df3
  GROUP BY
    dispatch_date_week
)
SELECT
  dispatch_date_week,
  sum_freight_cost_usd
FROM df4
