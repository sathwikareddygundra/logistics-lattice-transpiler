# Query: average TAT by carrier


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT invoice_number, carrier FROM vgu_dispatch")
    # n2 select
    df2 = read_sql("SELECT invoice_number, total_tat_hours FROM vgu_tat")
    # n3 join
    df3 = df1.merge(df2[["invoice_number", "total_tat_hours"]], on="invoice_number", how="inner")
    # n4 aggregate
    df4 = (
        df3.groupby(["carrier"], as_index=False)["total_tat_hours"]
        .sum()
        .rename(columns={"total_tat_hours": "sum_total_tat_hours"})
    )
    # n5 output
    df5 = df4[["carrier", "sum_total_tat_hours"]].reset_index(drop=True)
    return df5
