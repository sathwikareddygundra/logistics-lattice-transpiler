-- Query: monthly weight trend
WITH df1 AS (
  SELECT
    dispatch_date,
    shipment_weight_kg
  FROM ycw_dispatch
), df2 AS (
  SELECT
    *,
    STRFTIME(dispatch_date, '%Y-%m') AS dispatch_date_month
  FROM df1
), df3 AS (
  SELECT
    dispatch_date_month,
    SUM(shipment_weight_kg) AS sum_shipment_weight_kg
  FROM df2
  GROUP BY
    dispatch_date_month
)
SELECT
  dispatch_date_month,
  sum_shipment_weight_kg
FROM df3
