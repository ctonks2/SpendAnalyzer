import json
from pathlib import Path
import pandas as pd
from spend_analyzer.data_manager import DataManager


def test_smiths_json_mapping(tmp_path):
    # Smiths JSON with basket + items
    obj = {
        "basket": {
            "date": "2026-04-23",
            "store": "SmithsMarket",
            "orderno": "S123",
            "items": [
                {
                    "purchasedescription": "Apples",
                    "productupc": "000111222333",
                    "retailamt": "1.50",
                    "customerloyamt": "1.20",
                }
            ],
            "retailamt": "1.50",
            "customerloyamt": "1.20",
        }
    }
    p = tmp_path / "smiths.json"
    p.write_text(json.dumps(obj), encoding="utf-8")

    dm = DataManager()
    result = dm.import_file(str(p), user_id="u_smith")
    cnt = result.get("imported", 0)

    assert cnt == 1
    txs = dm.get_transactions_by_user("u_smith")
    assert len(txs) == 1
    tx = txs[0]
    assert tx.get("item_name") == "Apples"
    assert tx.get("product_upc") == "000111222333"
    assert float(tx.get("unit_price")) == 1.5
    assert float(tx.get("total_price")) == 1.2
    assert tx.get("orderno") == "S123"
    assert tx.get("store") == "SmithsMarket"


def test_maceys_excel_sheet2_mapping(tmp_path):
    # Create a two-sheet Excel file, with sheet2 containing the Macey data
    sheet1 = pd.DataFrame({"A": [1, 2]})
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
    p = tmp_path / "maceys.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as writer:
        sheet1.to_excel(writer, index=False, sheet_name="Sheet1")
        sheet2.to_excel(writer, index=False, sheet_name="Sheet2")

    dm = DataManager()
    result = dm.import_file(str(p), user_id="u_maceys")
    cnt = result.get("imported", 0)

    assert cnt == 1
    txs = dm.get_transactions_by_user("u_maceys")
    assert len(txs) == 1
    tx = txs[0]
    assert tx.get("item_name") == "Bananas"
    assert tx.get("product_upc") == "999888777666"
    assert float(tx.get("unit_price")) == 0.99
    assert float(tx.get("total_price")) == 0.89
    assert tx.get("orderno") == "M456"
    assert tx.get("store") == "Maceys"