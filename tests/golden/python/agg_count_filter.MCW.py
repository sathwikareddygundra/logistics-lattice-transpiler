# Query: how many delayed shipments
import pandas as pd


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT invoice_number, current_status FROM tracking")
    # n2 filter
    df2 = df1[df1["current_status"] == "Delayed"]
    # n3 aggregate
    df3 = pd.DataFrame({"count_invoice_number": [df2["invoice_number"].count()]})
    # n4 output
    df4 = df3[["count_invoice_number"]].reset_index(drop=True)
    return df4
