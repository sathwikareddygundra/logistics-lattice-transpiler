# Query: compare DHL and FedEx freight cost


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT carrier, freight_cost_usd FROM ycw_dispatch")
    # n2 aggregate
    df2 = (
        df1.groupby(["carrier"], as_index=False)["freight_cost_usd"]
        .sum()
        .rename(columns={"freight_cost_usd": "sum_freight_cost_usd"})
    )
    # n3 output
    df3 = df2[["carrier", "sum_freight_cost_usd"]].reset_index(drop=True)
    return df3
