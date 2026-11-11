# Query: which carrier has the most delayed shipments


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT invoice_number, carrier FROM ycw_dispatch")
    # n2 select
    df2 = read_sql("SELECT invoice_number, current_status FROM ycw_tracking")
    # n4 filter
    df4 = df2[df2["current_status"] == "Delayed"]
    # n3 join
    df3 = df4.merge(df1[["invoice_number", "carrier"]], on="invoice_number", how="inner")
    # n5 aggregate
    df5 = (
        df3.groupby(["carrier"], as_index=False)["invoice_number"]
        .count()
        .rename(columns={"invoice_number": "count_invoice_number"})
    )
    # n6 output
    df6 = df5[["carrier", "count_invoice_number"]].reset_index(drop=True)
    return df6
