-- Query: which carrier has the most delayed shipments
WITH df1 AS (
  SELECT
    invoice_number,
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
    current_status = 'Delayed'
), df5 AS (
  SELECT
    carrier,
    COUNT(invoice_number) AS count_invoice_number
  FROM df4
  GROUP BY
    carrier
)
SELECT
  carrier,
  count_invoice_number
FROM df5
