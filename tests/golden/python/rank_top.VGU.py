# Query: top 3 destinations by freight cost


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT destination_city, freight_cost_usd FROM vgu_dispatch")
    # n2 aggregate
    df2 = (
        df1.groupby(["destination_city"], as_index=False)["freight_cost_usd"]
        .sum()
        .rename(columns={"freight_cost_usd": "sum_freight_cost_usd"})
    )
    # n3 output
    df3 = df2[["destination_city", "sum_freight_cost_usd"]].reset_index(drop=True)
    return df3
