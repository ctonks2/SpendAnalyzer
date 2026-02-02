import os
import sqlite3
from pathlib import Path
from spend_analyzer.data_manager import DataManager
from spend_analyzer.migrate import migrate_transactions


def test_migrate_creates_tables_and_rows(tmp_path):
    dm = DataManager()
    # create two transactions with same orderno -> should map to one receipt with two line items
    tx1 = {
        "transaction_id": "tx_a",
        "user_id": "u1",
        "date": "2026-01-10",
        "store": "SmithsMarket",
        "item_name": "Apple",
        "product_upc": "UPC1",
        "unit_price": "1.00",
        "total_price": "0.90",
        "orderno": "S1",
    }
    tx2 = {
        "transaction_id": "tx_b",
        "user_id": "u1",
        "date": "2026-01-10",
        "store": "SmithsMarket",
        "item_name": "Banana",
        "product_upc": "UPC2",
        "unit_price": "2.00",
        "total_price": "1.80",
        "orderno": "S1",
    }
    dm.transactions.append(tx1)
    dm.transactions.append(tx2)

    dbfile = tmp_path / "test_db.sqlite"
    db_url = f"sqlite:///{dbfile}"

    res = migrate_transactions(dm.transactions, db_url=db_url)
    assert res["receipts"] == 1
    assert res["line_items"] == 2

    # Check DB content directly
    conn = sqlite3.connect(str(dbfile))
    cur = conn.cursor()
    cur.execute("SELECT id, store_id FROM receipts")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "S1"
    cur.execute("SELECT COUNT(*) FROM line_items")
    cnt = cur.fetchone()[0]
    assert cnt == 2
    conn.close()