"""Simple CLI for Spend Analyzer prototype"""
import os
import textwrap
from .data_manager import DataManager
from .llm_client import LLMClient
from .reports import ReportManager


def run_cli():
    dm = DataManager()
    llm = LLMClient()
    rm = ReportManager()

    print("Welcome to Spend Analyzer (CLI Prototype)")

    while True:
        print("\nSelect role:\n1) User\n2) Admin\n3) Exit")
        choice = input("Choice: ").strip()
        if choice == "1":
            user_id = input("Enter your user id (e.g., alice): ").strip() or "user"
            user_menu(dm, llm, rm, user_id)
        elif choice == "2":
            admin_password = os.getenv("SA_ADMIN_PASSWORD", "adminpass")
            pwd = input("Admin password: ")
            if pwd == admin_password:
                admin_menu(dm, llm, rm)
            else:
                print("Invalid password.")
        elif choice == "3":
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Try again.")


def user_menu(dm, llm, rm, user_id):
    while True:
        print(textwrap.dedent("""
        \nUser Menu:
        1) Upload a file (CSV, JSON, XLSX, PDF)
        2) Ask the LLM about my spending
        3) Generate a list of premade reports
        4) List my transactions (in-memory)
        5) Import all files from data/raw/
        6) Back
        """))
        choice = input("Choice: ").strip()
        if choice == "1":
            path = input("Path to file: ").strip()
            try:
                count = dm.import_file(path, user_id)
                print(f"Imported {count} transactions for user {user_id}.")
            except Exception as e:
                print("Error importing file:", e)
        elif choice == "2":
            q = input("Ask a question about your spending: ")
            context = dm.get_transactions_by_user(user_id)
            resp = llm.ask(q, context=context)
            print("LLM Response:\n", resp)
        elif choice == "3":
            print("Available reports: 1) spending_by_store 2) top_items")
            r = input("Choose report: ")
            report = rm.generate_report(r, dm, user_id)
            if report:
                path = rm.save_report(report, user_id, r)
                print(f"Report saved to {path}")
            else:
                print("Unknown report")
        elif choice == "4":
            # Listing submenu: Transactions, Common Stores, Receipts, Line Items
            while True:
                print(textwrap.dedent('''
                
                List Menu:
                1) Transactions (raw)
                2) Common stores (in-memory)
                3) Receipts summary (grouped by orderno)
                4) Line items summary (top products)
                5) Show DB stores/receipts/line_items (if DB available)
                6) Back
                '''))
                sub = input("Choice: ").strip()
                if sub == "1":
                    txs = dm.get_transactions_by_user(user_id)
                    print(f"Transactions ({len(txs)})")
                    for t in txs[:200]:
                        print(t)
                elif sub == "2":
                    from collections import Counter
                    txs = dm.get_transactions_by_user(user_id)
                    field_name = "store"
                    # Pair store number with source (inferred from filename) so you can see which source each store came from
                    store_pairs = [(t.get("store"), t.get("source")) for t in txs if t.get("store")]
                    counts = Counter(store_pairs)
                    print(f"Top stores (field: '{field_name}', showing source) (in-memory):")
                    for (store, source), cnt in counts.most_common(20):
                        src = source or "unknown"
                        print(f"{store} (source: {src}): {cnt}")
                    show_all = input("Show all store numbers with source? (y/N): ").strip().lower()
                    if show_all == "y":
                        print(f"All stores (field: '{field_name}', source):")
                        for (store, source), cnt in counts.items():
                            src = source or "unknown"
                            print(f"{store} (source: {src}): {cnt}")
                elif sub == "3":
                    from collections import defaultdict
                    txs = dm.get_transactions_by_user(user_id)
                    grouping_field = "orderno"  # grouping by order number when present

                    def _safe_float(v):
                        try:
                            return float(v)
                        except Exception:
                            return 0.0

                    receipts = defaultdict(lambda: {"count": 0, "store": None, "date": None, "line_items": [], "total_before": 0.0, "total_after": 0.0})

                    for t in txs:
                        rid = t.get(grouping_field) or t.get("transaction_id")
                        receipts[rid]["count"] += 1
                        receipts[rid]["store"] = receipts[rid]["store"] or t.get("store")
                        receipts[rid]["store_source"] = receipts[rid].get("store_source") or t.get("source")
                        receipts[rid]["date"] = receipts[rid]["date"] or t.get("date")

                        qty = _safe_float(t.get("quantity") or 1)
                        unit = _safe_float(t.get("unit_price") or t.get("retailamt") or 0)
                        total = _safe_float(t.get("total_price") or t.get("customerloyamt") or t.get("TransPrice") or (unit * qty))

                        receipts[rid]["total_before"] += unit * qty
                        receipts[rid]["total_after"] += total
                        receipts[rid]["line_items"].append({
                            "item": t.get("item_name") or t.get("purchasedescription") or t.get("Description"),
                            "upc": t.get("product_upc") or t.get("UPC"),
                            "qty": qty,
                            "unit": unit,
                            "total": total,
                            "store": t.get("store"),
                            "store_source": t.get("source"),
                        })

                    print(f"Receipts (grouping field: '{grouping_field}') ({len(receipts)}):")
                    for rid, info in list(receipts.items())[:50]:
                        store_src = f"{info.get('store')} (source: {info.get('store_source') or 'unknown'})"
                        print(f"id={rid}, items={info['count']}, store={store_src}, date={info['date']}, total_before={info['total_before']:.2f}, total_after={info['total_after']:.2f}")

                    choice_detail = input("Enter receipt id to show line items, 'a' to show all details, or Enter to continue: ").strip()
                    if choice_detail == "a":
                        for rid, info in receipts.items():
                            print("\n--- Receipt", rid, "---")
                            store_src = f"{info.get('store')} (source: {info.get('store_source') or 'unknown'})"
                            print(f"store={store_src}, date={info['date']}, items={info['count']}, total_before={info['total_before']:.2f}, total_after={info['total_after']:.2f}")
                            for li in info['line_items']:
                                print(f"  - {li['item']} (upc={li['upc']}) qty={li['qty']} unit={li['unit']:.2f} total={li['total']:.2f} store={li.get('store')} (source={li.get('store_source')})")
                    elif choice_detail:
                        rid = choice_detail
                        if rid in receipts:
                            info = receipts[rid]
                            store_src = f"{info.get('store')} (source: {info.get('store_source') or 'unknown'})"
                            print("\n--- Receipt", rid, "---")
                            print(f"store={store_src}, date={info['date']}, items={info['count']}, total_before={info['total_before']:.2f}, total_after={info['total_after']:.2f}")
                            for li in info['line_items']:
                                print(f"  - {li['item']} (upc={li['upc']}) qty={li['qty']} unit={li['unit']:.2f} total={li['total']:.2f} store={li.get('store')} (source={li.get('store_source')})")
                        else:
                            print("Receipt id not found in the current user's data.")
                elif sub == "4":
                    # Show individual line items: description, receiptID, amount(before), amount(after)
                    txs = dm.get_transactions_by_user(user_id)

                    def _safe_float(v):
                        try:
                            return float(v)
                        except Exception:
                            return 0.0

                    line_items = []
                    for t in txs:
                        name = t.get("item_name") or t.get("purchasedescription") or t.get("Description")
                        # Skip items without a real description
                        if not name:
                            continue
                        rid = t.get("orderno") or t.get("transaction_id")
                        amount_before = _safe_float(t.get("unit_price") or t.get("retailamt") or t.get("Price") or 0)
                        amount_after = _safe_float(t.get("total_price") or t.get("customerloyamt") or t.get("TransPrice") or (amount_before * _safe_float(t.get("quantity") or 1)))
                        line_items.append({"name": name, "receipt": rid, "before": amount_before, "after": amount_after})

                    print(f"Line items ({len(line_items)}):")
                    # Optionally filter by receipt id to see items connected to same receipt
                    filter_rid = input("Filter by receipt id (enter to skip): ").strip()
                    shown = 0
                    for it in line_items:
                        if filter_rid and str(it.get("receipt")) != filter_rid:
                            continue
                        # include store and source (join-like behavior)
                        # find a matching transaction for the same receipt to get store/source
                        store = None
                        source = None
                        for t in txs:
                            if (t.get("orderno") or t.get("transaction_id")) == it.get("receipt"):
                                store = t.get("store")
                                source = t.get("source")
                                break
                        print(f"{it['name']} | receipt={it['receipt']} | store={store} (source={source or 'unknown'}) | before={it['before']:.2f} | after={it['after']:.2f}")
                        shown += 1
                        if shown >= 500:
                            more = input("More items available. Continue? (y/N): ").strip().lower()
                            if more != "y":
                                break
                            shown = 0
                    if shown == 0:
                        print("No items matched the filter or no items available.")
                elif sub == "5":
                    # Attempt to show DB summaries if a DB exists
                    try:
                        from .db import get_session
                        from .models import Store, Receipt, LineItem
                        # default DB url used by migrate helpers
                        s = get_session("sqlite:///spend_analyzer.db")
                        store_cnt = s.query(Store).count()
                        receipt_cnt = s.query(Receipt).count()
                        line_cnt = s.query(LineItem).count()
                        print(f"DB summary: stores={store_cnt}, receipts={receipt_cnt}, line_items={line_cnt}")
                        # show top 10 stores
                        rows = s.query(Store).limit(10).all()
                        print("Sample stores:")
                        for r in rows:
                            print(r.id, r.name)
                    except Exception as e:
                        print("DB not available or error when querying DB:", e)
                elif sub == "6":
                    break
                else:
                    print("Invalid choice.")
        elif choice == "5":
            results = dm.import_all_from_raw(user_id)
            print("Import results:")
            for fname, res in results.items():
                print(f"{fname}: {res}")
        elif choice == "6":
            break
        else:
            print("Invalid choice.")


def admin_menu(dm, llm, rm):
    import argparse
    from . import migrate as migrate_module

    while True:
        print(textwrap.dedent("""
        \nAdmin Menu:
        1) View all transactions
        2) Ask the LLM (admin-wide)
        3) Define a new premade report (prompt LLM for ideas)
        4) Migrate in-memory transactions to DB
        5) Back
        """))
        choice = input("Choice: ").strip()
        if choice == "1":
            print(f"Total transactions: {len(dm.transactions)}")
        elif choice == "2":
            q = input("Ask LLM about global data: ")
            resp = llm.ask(q, context=dm.transactions)
            print(resp)
        elif choice == "3":
            prompt = input("Describe the new report you want: ")
            resp = llm.ask(prompt, context=dm.transactions)
            print("LLM suggestion:\n", resp)
        elif choice == "4":
            db_url = input("DB URL (e.g., sqlite:///spend_analyzer.db): ").strip() or "sqlite:///spend_analyzer.db"
            print("Migrating transactions to", db_url)
            res = migrate_module.migrate_transactions(dm.transactions, db_url=db_url)
            print("Migration result:", res)
        elif choice == "5":
            break
        else:
            print("Invalid choice.")
