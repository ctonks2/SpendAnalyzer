import pandas as pd
from spend_analyzer.data_manager import DataManager


def test_maceys_store_number_extracted(tmp_path):
    sheet1 = pd.DataFrame({"A": [1]})
    sheet2 = pd.DataFrame(
        {
            "Store": ["010990 (MACEYS SOUTH OGDEN)"],
            "Date": ["2026-05-01"],
            "Trans": ["M789"],
            "UPC": ["999888777666"],
            "Description": ["Grapes"],
            "Price": ["1.99"],
            "TransPrice": ["1.89"],
            "GrandTotal": ["1.89"],
        }
    )
    p = tmp_path / "Maceys_20260501.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as writer:
        sheet1.to_excel(writer, index=False, sheet_name="Sheet1")
        sheet2.to_excel(writer, index=False, sheet_name="Sheet2")

    dm = DataManager()
    cnt = dm.import_file(str(p), user_id="u_maceys")

    assert cnt == 1
    tx = dm.get_transactions_by_user("u_maceys")[0]
    assert tx.get("store") == "010990"
    assert tx.get("source") == "Maceys"