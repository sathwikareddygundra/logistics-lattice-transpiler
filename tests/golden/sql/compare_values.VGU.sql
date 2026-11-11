-- Query: compare DHL and FedEx freight cost
WITH df1 AS (
  SELECT
    carrier,
    freight_cost_usd
  FROM vgu_dispatch
), df2 AS (
  SELECT
    carrier,
    SUM(freight_cost_usd) AS sum_freight_cost_usd
  FROM df1
  GROUP BY
    carrier
)
SELECT
  carrier,
  sum_freight_cost_usd
FROM df2
