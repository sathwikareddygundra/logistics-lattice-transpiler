-- Query: top 3 destinations by freight cost
WITH df1 AS (
  SELECT
    destination_city,
    freight_cost_usd
  FROM ycw_dispatch
), df2 AS (
  SELECT
    destination_city,
    SUM(freight_cost_usd) AS sum_freight_cost_usd
  FROM df1
  GROUP BY
    destination_city
)
SELECT
  destination_city,
  sum_freight_cost_usd
FROM df2
