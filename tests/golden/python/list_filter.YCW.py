# Query: list shipments from Chicago in July 2026


def run(read_sql):
    # n1 select
    df1 = read_sql(
        "SELECT invoice_number, dispatch_date, origin_warehouse, destination_city, carrier FROM ycw_dispatch"
    )
    # n2 filter
    df2 = df1[df1["origin_warehouse"] == "Chicago_WH"]
    # n3 filter
    df3 = df2[df2["dispatch_date"] >= "2026-07-01"]
    # n4 filter
    df4 = df3[df3["dispatch_date"] < "2026-08-01"]
    # n5 sort
    df5 = df4.sort_values(by=["invoice_number"], ascending=True, kind="stable")
    # n6 limit
    df6 = df5.head(20)
    # n7 output
    df7 = df6[
        ["invoice_number", "dispatch_date", "origin_warehouse", "destination_city", "carrier"]
    ].reset_index(drop=True)
    return df7
