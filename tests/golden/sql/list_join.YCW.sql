-- Query: show delayed shipments from Atlanta
WITH df1 AS (
  SELECT
    invoice_number,
    dispatch_date,
    origin_warehouse,
    destination_city,
    carrier
  FROM ycw_dispatch
), df2 AS (
  SELECT
    invoice_number,
    current_status
  FROM ycw_tracking
), df3 AS (
  SELECT
    l.*,
    r.current_status
  FROM df1 AS l
  INNER JOIN df2 AS r
    ON l.invoice_number = r.invoice_number
), df4 AS (
  SELECT
    *
  FROM df3
  WHERE
    origin_warehouse = 'Atlanta_WH'
), df5 AS (
  SELECT
    *
  FROM df4
  WHERE
    current_status = 'Delayed'
)
SELECT
  invoice_number,
  dispatch_date,
  origin_warehouse,
  destination_city,
  carrier,
  current_status
FROM df5
ORDER BY
  invoice_number ASC
LIMIT 20
