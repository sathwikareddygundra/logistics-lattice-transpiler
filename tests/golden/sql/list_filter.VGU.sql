-- Query: list shipments from Chicago in July 2026
WITH df1 AS (
  SELECT
    invoice_number,
    dispatch_date,
    origin_warehouse,
    destination_city,
    carrier
  FROM vgu_dispatch
), df2 AS (
  SELECT
    *
  FROM df1
  WHERE
    origin_warehouse = 'Chicago_WH'
), df3 AS (
  SELECT
    *
  FROM df2
  WHERE
    dispatch_date >= '2026-07-01'
), df4 AS (
  SELECT
    *
  FROM df3
  WHERE
    dispatch_date < '2026-08-01'
)
SELECT
  invoice_number,
  dispatch_date,
  origin_warehouse,
  destination_city,
  carrier
FROM df4
ORDER BY
  invoice_number ASC
LIMIT 20
