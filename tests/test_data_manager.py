import json
from pathlib import Path
from spend_analyzer.data_manager import DataManager


def test_import_malformed_json_recovers(tmp_path):
    # Malformed JSON with trailing commas and a stray number line
    text = '{ "items": [ { "item": "A", "total": "1.0", }, { "item": "B", "total": "2.0", }, ], }\n123\n'
    p = tmp_path / "malformed.json"
    p.write_text(text, encoding="utf-8")

    dm = DataManager()
    cnt = dm.import_file(str(p), user_id="u1")

    assert cnt == 2
    txs = dm.get_transactions_by_user("u1")
    assert len(txs) == 2
    items = [t.get("item_name") for t in txs]
    # item_name mapping uses DEFAULT_MAPPING ("item" -> item_name)
    assert "A" in items and "B" in items


def test_import_nested_items_extracted(tmp_path):
    # Nested structure containing items in deeper keys
    nested = {
        "customer": [
            {
                "basket": [
                    {
                        "date": "2026-01-01",
                        "store": "NestedShop",
                        "items": [
                            {"item": "NestedProduct", "total": "3.33"}
                        ],
                    }
                ]
            }
        ]
    }
    p = tmp_path / "nested.json"
    p.write_text(json.dumps(nested), encoding="utf-8")

    dm = DataManager()
    cnt = dm.import_file(str(p), user_id="u2")

    assert cnt == 1
    txs = dm.get_transactions_by_user("u2")
    assert len(txs) == 1
    tx = txs[0]
    assert tx.get("item_name") == "NestedProduct"
    assert tx.get("date") == "2026-01-01"
    assert tx.get("store") == "NestedShop"