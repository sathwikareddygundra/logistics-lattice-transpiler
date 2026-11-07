# Query: total freight cost by carrier in August 2026


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT dispatch_date, carrier, freight_cost_usd FROM ycw_dispatch")
    # n2 filter
    df2 = df1[df1["dispatch_date"] >= "2026-08-01"]
    # n3 filter
    df3 = df2[df2["dispatch_date"] < "2026-09-01"]
    # n4 aggregate
    df4 = (
        df3.groupby(["carrier"], as_index=False)["freight_cost_usd"]
        .sum()
        .rename(columns={"freight_cost_usd": "sum_freight_cost_usd"})
    )
    # n5 output
    df5 = df4[["carrier", "sum_freight_cost_usd"]].reset_index(drop=True)
    return df5
