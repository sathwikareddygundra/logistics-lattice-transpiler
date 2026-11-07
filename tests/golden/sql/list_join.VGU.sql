-- Query: show delayed shipments from Atlanta
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
    invoice_number,
    current_status
  FROM vgu_tracking
), df4 AS (
  SELECT
    *
  FROM df1
  WHERE
    origin_warehouse = 'Atlanta_WH'
), df5 AS (
  SELECT
    *
  FROM df2
  WHERE
    current_status = 'Delayed'
), df3 AS (
  SELECT
    l.*,
    r.current_status
  FROM df4 AS l
  INNER JOIN df5 AS r
    ON l.invoice_number = r.invoice_number
)
SELECT
  invoice_number,
  dispatch_date,
  origin_warehouse,
  destination_city,
  carrier,
  current_status
FROM df3
ORDER BY
  invoice_number ASC
LIMIT 20
