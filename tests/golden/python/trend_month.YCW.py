# Query: monthly weight trend
import pandas as pd


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT dispatch_date, shipment_weight_kg FROM ycw_dispatch")
    # n2 window
    df2 = df1.assign(dispatch_date_month=pd.to_datetime(df1["dispatch_date"]).dt.strftime("%Y-%m"))
    # n3 aggregate
    df3 = (
        df2.groupby(["dispatch_date_month"], as_index=False)["shipment_weight_kg"]
        .sum()
        .rename(columns={"shipment_weight_kg": "sum_shipment_weight_kg"})
    )
    # n4 output
    df4 = df3[["dispatch_date_month", "sum_shipment_weight_kg"]].reset_index(drop=True)
    return df4
