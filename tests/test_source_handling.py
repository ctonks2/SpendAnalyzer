import json
import pandas as pd
from spend_analyzer.data_manager import DataManager


def test_smiths_store_number_and_source(tmp_path):
    obj = {
        "basket": {
            "date": "2026-04-23",
            "store": "Store 6789",
            "orderno": "S123",
            "items": [
                {"item": "Apples", "total": "1.50"}
            ]
        }
    }
    p = tmp_path / "Smiths_20260423.json"
    p.write_text(json.dumps(obj), encoding="utf-8")

    dm = DataManager()
    result = dm.import_file(str(p), user_id="u_smith")
    cnt = result.get("imported", 0)

    assert cnt == 1
    tx = dm.get_transactions_by_user("u_smith")[0]
    # Smiths store should be digits-only
    assert tx.get("store") == "6789"
    # source should be set to the filename first token
    assert tx.get("source") == "Smiths"


def test_maceys_source_added_from_excel(tmp_path):
    sheet1 = pd.DataFrame({"A": [1]})
    sheet2 = pd.DataFrame(
        {
            "Store": ["Maceys"],
            "Date": ["2026-05-01"],
            "Trans": ["M456"],
            "UPC": ["999888777666"],
            "Description": ["Bananas"],
            "Price": ["0.99"],
            "TransPrice": ["0.89"],
            "GrandTotal": ["0.89"],
        }
    )
    p = tmp_path / "Maceys_20260501.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as writer:
        sheet1.to_excel(writer, index=False, sheet_name="Sheet1")
        sheet2.to_excel(writer, index=False, sheet_name="Sheet2")

    dm = DataManager()
    result = dm.import_file(str(p), user_id="u_maceys")
    cnt = result.get("imported", 0)

    assert cnt == 1
    tx = dm.get_transactions_by_user("u_maceys")[0]
    assert tx.get("store") == "Maceys"
    assert tx.get("source") == "Maceys"