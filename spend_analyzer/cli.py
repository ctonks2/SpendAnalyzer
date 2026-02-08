"""Simple CLI for Spend Analyzer prototype"""
import os
import json
from collections import Counter, defaultdict
from .data_manager import DataManager
from .llm_client import LLMClient
from .llm_menu import LLMMenu
from .files import FilesManager


def _show_menu(menu_dict, title=None):
    """Display menu options from dictionary"""
    if title:
        print(f"\n{title}")
    for choice, (description, _) in sorted(menu_dict.items()):
        print(f"{choice}) {description}")
        

def _run_menu(menu_dict):
    """Run a menu loop with dictionary of {choice: (description, handler_func)}
    
    Returns when user selects 'back' or menu returns 'back' signal
    """
    while True:
        _show_menu(menu_dict)
        choice = input("Choice: ").strip()
        
        if choice in menu_dict:
            _, handler = menu_dict[choice]
            result = handler()
            if result == "back":
                break
        else:
            print("Invalid choice. Try again.")


def run_cli():
    dm = DataManager()
    llm = LLMClient()

    print("Welcome to Spend Analyzer (CLI Prototype)")

    def role_user():
        user_id = input("Enter your user id (e.g., alice): ").strip() or "user"
        user_menu(dm, llm, user_id)
        return None

    def role_admin():
        print("Admin menu is currently disabled.")
        return None

    def role_exit():
        print("Goodbye!")
        return "exit"

    menu = {
        "1": ("User", role_user),
        "2": ("Admin", role_admin),
        "3": ("Exit", role_exit),
    }

    while True:
        _show_menu(menu, "Select role:")
        choice = input("Choice: ").strip()
        
        if choice in menu:
            _, handler = menu[choice]
            if handler() == "exit":
                break
        else:
            print("Invalid choice. Try again.")



def files_menu(dm, user_id):
    files_manager = FilesManager(dm)
    menu = {
        "1": ("Upload single receipt", lambda: _persist_and_report(files_manager.upload_single_receipt(user_id), dm)),
        "2": ("Select one from raw data", lambda: files_manager.select_one_from_raw(user_id)),
        "3": ("Select all from raw data", lambda: files_manager.select_all_from_raw(user_id)),
        "4": ("Back", lambda: "back"),
    }
    def _persist_and_report(txs, dm):
        if not txs:
            print("No transactions created.")
            return
        if hasattr(dm, "transactions") and isinstance(dm.transactions, list):
            dm.transactions.extend(txs)
            print(f"Appended {len(txs)} transactions to in-memory store.")
        else:
            print("Could not persist transactions: DataManager has no supported API.")
    _run_menu(menu)


def user_menu(dm, llm, user_id):
    """User menu with main options"""


    def files_option():
        return files_menu(dm, user_id)

    llm_menu = LLMMenu(llm, dm)
    def ask_llm():
        return llm_menu.ask_llm(user_id)

    def generate_reports():
        # Load recommendations and let the user choose a category to view
        rec_file = os.path.join(os.getcwd(), "reports", "recommendations.json")
        if not os.path.exists(rec_file):
            print("No recommendations found (reports/recommendations.json missing).")
            return None

        try:
            with open(rec_file, "r", encoding="utf-8") as f:
                recs = json.load(f)
        except Exception as e:
            print(f"Error reading recommendations: {e}")
            return None

        # Group by category
        grouped = {}
        for r in recs:
            cat = r.get("category", "Uncategorized")
            grouped.setdefault(cat, []).append(r)

        categories = sorted(grouped.keys())
        total_count = len(recs)
        print("\nView Recommendations:\n")
        print(f"0) All ({total_count})")
        for i, cat in enumerate(categories, 1):
            print(f"{i}) {cat} ({len(grouped[cat])})")

        choice = input("Select category number (default 0): ").strip() or "0"
        try:
            idx = int(choice)
        except Exception:
            idx = 0

        if idx == 0:
            selected_items = recs
            header = f"All Recommendations ({len(selected_items)})"
            selected_cat = None
        elif 1 <= idx <= len(categories):
            selected_cat = categories[idx - 1]
            selected_items = grouped[selected_cat]
            header = f"{selected_cat} ({len(selected_items)})"
        else:
            print("Invalid selection.")
            return None

        import textwrap

        print("\n" + "=" * 60)
        print(header)
        print("=" * 60 + "\n")

        for i, item in enumerate(selected_items, 1):
            date = item.get("date") or item.get("saved_at", "")
            q = item.get("question", "")
            resp = item.get("response", "") or ""

            print(f"{i}) Date: {date}")
            print(f"   Question: {q}")
            print("   Advice:")

            # Special, cleaner formatting for Budget Tips: enumerate lines if present
            if (selected_cat == "Budget Tips") or (item.get("category") == "Budget Tips"):
                lines = [ln.strip() for ln in resp.splitlines() if ln.strip()]
                if lines:
                    for j, ln in enumerate(lines, 1):
                        wrapped = textwrap.fill(ln, width=76, initial_indent="      ", subsequent_indent="      ")
                        print(f"     {j}. {wrapped.lstrip()}")
                else:
                    wrapped = textwrap.fill(resp, width=76, initial_indent="      ", subsequent_indent="      ")
                    print(wrapped)
            else:
                wrapped = textwrap.fill(resp, width=76, initial_indent="      ", subsequent_indent="      ")
                print(wrapped)

            print("-" * 60)

        return None

    def transactions_option():
        list_menu(dm, user_id)
        return None

    menu = {
        "1": ("Upload Files", files_option),
        "2": ("Ask LLM", ask_llm),
        "3": ("Generate Reports", generate_reports),
        "4": ("Transactions Menu", transactions_option),
        "5": ("Back", lambda: "back"),
    }

    _run_menu(menu)


def list_menu(dm, user_id):
    """Submenu for listing transactions, stores, receipts, and line items"""
    
    def _safe_float(v):
        try:
            return float(v)
        except Exception:
            return 0.0

    def show_transactions():
        txs = dm.get_transactions_by_user(user_id)
        print(f"Transactions ({len(txs)}) this is for testing to show data")
        for t in txs[:200]:
            print(t)
        return None

    def show_stores():
        txs = dm.get_transactions_by_user(user_id)
        store_pairs = [(t.get("store"), t.get("source")) for t in txs if t.get("store")]
        counts = Counter(store_pairs)
        print(f"Top stores (showing source) (in-memory):")
        for (store, source), cnt in counts.most_common(20):
            src = source or "unknown"
            print(f"{store} (source: {src}): {cnt}")
        show_all = input("Show all store numbers with source? (y/N): ").strip().lower()
        if show_all == "y":
            print(f"All stores (source):")
            for (store, source), cnt in counts.items():
                src = source or "unknown"
                print(f"{store} (source: {src}): {cnt}")
        return None

    def show_receipts():
        txs = dm.get_transactions_by_user(user_id)
        grouping_field = "orderno"
        receipts = defaultdict(lambda: {
            "count": 0, "store": None, "date": None, 
            "line_items": [], "total_before": 0.0, "total_after": 0.0,
            "has_receipt_total": False
        })

        for t in txs:
            rid = t.get(grouping_field) or t.get("transaction_id")
            # If this transaction is a receipt-level total marker, record it separately
            is_receipt_total = (str(t.get("item_name") or "").upper() == "RECEIPT_TOTAL")

            receipts[rid]["store"] = receipts[rid]["store"] or t.get("store")
            receipts[rid]["store_source"] = receipts[rid].get("store_source") or t.get("source")
            receipts[rid]["date"] = receipts[rid]["date"] or t.get("date")

            qty = _safe_float(t.get("quantity") or 1)
            unit = _safe_float(t.get("unit_price") or t.get("retailamt") or 0)
            total = _safe_float(t.get("total_price") or t.get("customerloyamt") or 
                              t.get("TransPrice") or (unit * qty))

            if is_receipt_total:
                # Prefer the explicit receipt total when present; don't append as a line item
                receipts[rid]["total_after"] = total
                receipts[rid]["has_receipt_total"] = True
            else:
                receipts[rid]["count"] += 1
                receipts[rid]["total_before"] += unit * qty
                # Only add to total_after when no explicit receipt total exists
                if not receipts[rid]["has_receipt_total"]:
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

        print(f"Receipts ({len(receipts)}):")
        for rid, info in list(receipts.items())[:50]:
            store_src = f"{info.get('store')} (source: {info.get('store_source') or 'unknown'})"
            print(f"id={rid}, items={info['count']}, store={store_src}, date={info['date']}, "
                  f"total_before={info['total_before']:.2f}, total_after={info['total_after']:.2f}")

        choice_detail = input("Enter receipt id to show line items, 'a' to show all details, or Enter to continue: ").strip()
        if choice_detail == "a":
            for rid, info in receipts.items():
                print("\n--- Receipt", rid, "---")
                store_src = f"{info.get('store')} (source: {info.get('store_source') or 'unknown'})"
                print(f"store={store_src}, date={info['date']}, items={info['count']}, "
                      f"total_before={info['total_before']:.2f}, total_after={info['total_after']:.2f}")
                for li in info['line_items']:
                    print(f"  - {li['item']} (upc={li['upc']}) qty={li['qty']} unit={li['unit']:.2f} "
                          f"total={li['total']:.2f})")
        elif choice_detail:
            rid = choice_detail
            if rid in receipts:
                info = receipts[rid]
                store_src = f"{info.get('store')} (source: {info.get('store_source') or 'unknown'})"
                print("\n--- Receipt", rid, "---")
                print(f"store={store_src}, date={info['date']}, items={info['count']}, "
                      f"total_before={info['total_before']:.2f}, total_after={info['total_after']:.2f}")
                for li in info['line_items']:
                    print(f"  - {li['item']} (upc={li['upc']}) qty={li['qty']} unit={li['unit']:.2f} "
                          f"total={li['total']:.2f})")
            else:
                print("Receipt id not found in the current user's data.")
        return None

    def show_line_items():
        txs = dm.get_transactions_by_user(user_id)
        line_items = []
        for t in txs:
            name = t.get("item_name") or t.get("purchasedescription") or t.get("Description")
            # Skip receipt-level total markers from line item listing
            if str(name).upper() == "RECEIPT_TOTAL":
                continue
            if not name:
                continue
            rid = t.get("orderno") or t.get("transaction_id")
            amount_before = _safe_float(t.get("unit_price") or t.get("retailamt") or t.get("Price") or 0)
            amount_after = _safe_float(t.get("total_price") or t.get("customerloyamt") or 
                                      t.get("TransPrice") or (amount_before * _safe_float(t.get("quantity") or 1)))
            line_items.append({"name": name, "receipt": rid, "before": amount_before, "after": amount_after})

        print(f"Line items ({len(line_items)}):")
        filter_rid = input("Filter by receipt id (enter to skip): ").strip()
        shown = 0
        for it in line_items:
            if filter_rid and str(it.get("receipt")) != filter_rid:
                continue
            store = None
            source = None
            for t in txs:
                if (t.get("orderno") or t.get("transaction_id")) == it.get("receipt"):
                    store = t.get("store")
                    source = t.get("source")
                    break
            print(f"{it['name']} | receipt={it['receipt']} | store={store} (source={source or 'unknown'}) | "
                  f"before={it['before']:.2f} | after={it['after']:.2f}")
            shown += 1
            if shown >= 500:
                more = input("More items available. Continue? (y/N): ").strip().lower()
                if more != "y":
                    break
                shown = 0
        if shown == 0:
            print("No items matched the filter or no items available.")
        return None

    def show_db():
        try:
            from .db import get_session
            from .models import Store, Receipt, LineItem
            s = get_session("sqlite:///spend_analyzer.db")
            store_cnt = s.query(Store).count()
            receipt_cnt = s.query(Receipt).count()
            line_cnt = s.query(LineItem).count()
            print(f"DB summary: stores={store_cnt}, receipts={receipt_cnt}, line_items={line_cnt}")
            rows = s.query(Store).limit(10).all()
            print("Sample stores:")
            for r in rows:
                print(r.id, r.name)
        except Exception as e:
            print("DB not available or error when querying DB:", e)
        return None

    menu = {
        "1": ("Common stores (in-memory)", show_stores),
        "2": ("Receipts summary (grouped by orderno)", show_receipts),
        "3": ("Line items summary (top products)", show_line_items),
        "4": ("Show DB stores/receipts/line_items (if DB available)", show_db),
        "5": ("Back", lambda: "back"),
    }

    _run_menu(menu)


def admin_menu(dm, llm):
    """Admin menu for managing transactions and reports"""
    from . import migrate as migrate_module

    def view_all():
        print(f"Total transactions: {len(dm.transactions)}")
        return None

    def ask_llm_admin():
        q = input("Ask LLM about global data: ")
        resp = llm.ask(q, context=dm.transactions)
        print(resp)
        return None

    def define_report():
        prompt = input("Describe the new report you want: ")
        resp = llm.ask(prompt, context=dm.transactions)
        print("LLM suggestion:\n", resp)
        return None

    def migrate_db():
        db_url = input("DB URL (e.g., sqlite:///spend_analyzer.db): ").strip() or "sqlite:///spend_analyzer.db"
        print("Migrating transactions to", db_url)
        res = migrate_module.migrate_transactions(dm.transactions, db_url=db_url)
        print("Migration result:", res)
        return None

    menu = {
        "1": ("View all transactions", view_all),
        "2": ("Ask the LLM (admin-wide)", ask_llm_admin),
        "3": ("Define a new premade report (prompt LLM for ideas)", define_report),
        "4": ("Migrate in-memory transactions to DB", migrate_db),
        "5": ("Back", lambda: "back"),
    }

    _run_menu(menu)
