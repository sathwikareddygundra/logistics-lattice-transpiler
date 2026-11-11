# Query: show delayed shipments from Atlanta


def run(read_sql):
    # n1 select
    df1 = read_sql(
        "SELECT invoice_number, dispatch_date, origin_warehouse, destination_city, carrier FROM ycw_dispatch"
    )
    # n2 select
    df2 = read_sql("SELECT invoice_number, current_status FROM ycw_tracking")
    # n4 filter
    df4 = df1[df1["origin_warehouse"] == "Atlanta_WH"]
    # n5 filter
    df5 = df2[df2["current_status"] == "Delayed"]
    # n3 join
    df3 = df4.merge(df5[["invoice_number", "current_status"]], on="invoice_number", how="inner")
    # n6 sort
    df6 = df3.sort_values(by=["invoice_number"], ascending=True, kind="stable")
    # n7 limit
    df7 = df6.head(20)
    # n8 output
    df8 = df7[
        [
            "invoice_number",
            "dispatch_date",
            "origin_warehouse",
            "destination_city",
            "carrier",
            "current_status",
        ]
    ].reset_index(drop=True)
    return df8
