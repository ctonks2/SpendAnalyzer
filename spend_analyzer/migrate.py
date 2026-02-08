"""Migration helper: persist in-memory transactions into a SQLite DB using SQLAlchemy"""
import uuid
from datetime import datetime
from .db import get_engine, get_session, Base
from .models import Store, Receipt, LineItem


def _cents(val):
    try:
        return int(round(float(val) * 100))
    except Exception:
        return None


def init_db(db_url="sqlite:///spend_analyzer.db"):
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)


def migrate_transactions(transactions, db_url="sqlite:///spend_analyzer.db"):
    """Persist transactions list into DB. Returns counts dict."""
    init_db(db_url)
    session = get_session(db_url)

    # Ensure stores and receipts and items
    # Group transactions by orderno if present, otherwise by synthetic receipt id
    receipts_map = {}

    for tx in transactions:
        orderno = tx.get("orderno")
        store_id = tx.get("store") or tx.get("merchant") or "unknown"
        if orderno:
            rid = orderno
        else:
            # use transaction id as receipt id when no explicit orderno
            rid = f"receipt_{tx.get('transaction_id') or uuid.uuid4()}"

        if rid not in receipts_map:
            receipts_map[rid] = {
                "store_id": store_id,
                "date": tx.get("date"),
                "line_items": [],
            }
        receipts_map[rid]["line_items"].append(tx)

    created_counts = {"stores": 0, "receipts": 0, "line_items": 0}

    for rid, info in receipts_map.items():
        store_id = str(info.get("store_id") or "unknown")

        # upsert store
        store = session.get(Store, store_id)
        if not store:
            store = Store(id=store_id, name=store_id)
            session.add(store)
            created_counts["stores"] += 1

        # determine receipt totals by summing line items or using item-level totals
        total_before = 0
        total_after = 0
        any_price = False
        for item in info["line_items"]:
            ub = item.get("unit_price") or item.get("retailamt") or item.get("price")
            tp = item.get("total_price") or item.get("customerloyamt") or item.get("TransPrice")
            ub_c = _cents(ub) if ub is not None else None
            tp_c = _cents(tp) if tp is not None else None
            if ub_c:
                total_before += ub_c
                any_price = True
            if tp_c:
                total_after += tp_c
                any_price = True

        receipt = session.get(Receipt, rid)
        if not receipt:
            rdate = None
            try:
                if info.get("date"):
                    rdate = datetime.fromisoformat(info.get("date")).date()
            except Exception:
                rdate = None
            receipt = Receipt(
                id=rid,
                store_id=store_id,
                date=rdate,
                total_before_cents=total_before if any_price else None,
                total_after_cents=total_after if any_price else None,
            )
            session.add(receipt)
            created_counts["receipts"] += 1

        # insert line items
        for item in info["line_items"]:
            li_id = item.get("transaction_id") or str(uuid.uuid4())
            li = session.get(LineItem, li_id)
            if li:
                continue
            ub = item.get("unit_price") or item.get("retailamt") or item.get("price")
            tp = item.get("total_price") or item.get("customerloyamt") or item.get("TransPrice")
            li = LineItem(
                id=str(li_id),
                receipt_id=rid,
                product_upc=str(item.get("product_upc")) if item.get("product_upc") is not None else None,
                description=item.get("item_name") or item.get("purchasedescription") or item.get("Description"),
                quantity=int(item.get("quantity") or 1),
                unit_price_cents=_cents(ub) if ub is not None else None,
                total_price_cents=_cents(tp) if tp is not None else None,
                category=item.get("category"),
            )
            session.add(li)
            created_counts["line_items"] += 1

    session.commit()
    session.close()
    return created_counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate in-memory transactions into a SQLite DB")
    parser.add_argument("--db", default="sqlite:///spend_analyzer.db", help="DB URL (default sqlite:///spend_analyzer.db)")
    args = parser.parse_args()

    # Best-effort: try to import existing in-memory saved transactions from a JSON file if present
    import os
    import json

    txs = []
    if os.path.exists("transactions.json"):
        with open("transactions.json", "r", encoding="utf-8") as fh:
            txs = json.load(fh)
    else:
        print("No transactions.json found; nothing to migrate when run as script.")
        exit(0)

    print("Migrating", len(txs), "transactions to", args.db)
    res = migrate_transactions(txs, db_url=args.db)
    print("Created:", res)