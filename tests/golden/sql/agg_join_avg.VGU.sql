-- Query: average TAT by carrier
WITH df1 AS (
  SELECT
    invoice_number,
    carrier
  FROM vgu_dispatch
), df2 AS (
  SELECT
    invoice_number,
    total_tat_hours
  FROM vgu_tat
), df3 AS (
  SELECT
    l.*,
    r.total_tat_hours
  FROM df1 AS l
  INNER JOIN df2 AS r
    ON l.invoice_number = r.invoice_number
), df4 AS (
  SELECT
    carrier,
    SUM(total_tat_hours) AS sum_total_tat_hours
  FROM df3
  GROUP BY
    carrier
)
SELECT
  carrier,
  sum_total_tat_hours
FROM df4
