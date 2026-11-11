-- Query: compare MCW and YCW freight cost
WITH df1 AS (
  SELECT
    freight_cost_usd
  FROM vgu_dispatch
), df2 AS (
  SELECT
    SUM(freight_cost_usd) AS sum_freight_cost_usd
  FROM df1
)
SELECT
  sum_freight_cost_usd
FROM df2
