-- Query: how many delayed shipments
WITH df1 AS (
  SELECT
    invoice_number,
    current_status
  FROM ycw_tracking
), df2 AS (
  SELECT
    *
  FROM df1
  WHERE
    current_status = 'Delayed'
), df3 AS (
  SELECT
    COUNT(invoice_number) AS count_invoice_number
  FROM df2
)
SELECT
  count_invoice_number
FROM df3
