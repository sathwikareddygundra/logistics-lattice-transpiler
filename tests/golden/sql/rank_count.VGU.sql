-- Query: which carrier has the most delayed shipments
WITH df1 AS (
  SELECT
    invoice_number,
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
  FROM df2
  WHERE
    current_status = 'Delayed'
), df3 AS (
  SELECT
    l.*,
    r.carrier
  FROM df4 AS l
  INNER JOIN df1 AS r
    ON l.invoice_number = r.invoice_number
), df5 AS (
  SELECT
    carrier,
    COUNT(invoice_number) AS count_invoice_number
  FROM df3
  GROUP BY
    carrier
)
SELECT
  carrier,
  count_invoice_number
FROM df5
