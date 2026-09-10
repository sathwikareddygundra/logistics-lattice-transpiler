# Source Schema Inventory (T-9)

Three source extracts, one shipment lifecycle, joined by `Invoice_Number`:

- **dispatch** — shipment origin, destination, carrier, weight, cost
- **tracking** — checkpoint status and location over time
- **turnaround_time** — SLA timing: promised vs actual delivery, load/unload duration

## Join integrity
All three files contain the exact same 10,000 `Invoice_Number` values — a clean 1:1:1 join, no orphans in either direction. Verified by full set-difference check, not just row counts.

## Known data quality issues to resolve before T-10 (canonical model)
1. `Dispatch_Date` is duplicated identically in `dispatch` and `turnaround_time`.
2. `tracking.Last_Known_Location` mixes hub codes and city names in one column.
3. `turnaround_time.Total_TAT_Hours` only takes 22 distinct values — likely bucketed, not raw elapsed time.
4. No dimension table for drivers, warehouses, or carriers — those currently only exist as string values embedded in the fact-like rows above.
