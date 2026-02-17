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
        choice = input("Enter your choice: ").strip()
        
        if choice in menu_dict:
            _, handler = menu_dict[choice]
            result = handler()
            if result == "back":
                break
        else:
            print("\nThat's not a valid option. Please select a number from the menu.")


def run_cli():
    dm = DataManager()
    llm = LLMClient()

    print("\n" + "=" * 60)
    print("         Welcome to Spend Analyzer")
    print("    Your Personal Spending Intelligence Tool")
    print("=" * 60)
    print("\nTrack receipts, analyze spending patterns, and get")
    print("AI-powered insights to make smarter financial decisions.\n")

    def role_user():
        print("\n" + "-" * 40)
        print("Please enter your User ID to get started.")
        print("This helps us save and retrieve your data.")
        print("-" * 40)
        user_id = input("Your User ID: ").strip() or "user"
        dm.load_user_data(user_id)
        user_menu(dm, llm, user_id)
        return None

    def role_admin():
        print("\nAdmin features are currently unavailable.")
        return None

    def role_exit():
        print("\nThank you for using Spend Analyzer. Goodbye!")
        return "exit"

    menu = {
        "1": ("Continue as User", role_user),
        "2": ("Admin Access", role_admin),
        "3": ("Exit Application", role_exit),
    }

    while True:
        _show_menu(menu, "\nHow would you like to proceed?")
        choice = input("Enter your choice: ").strip()
        
        if choice in menu:
            _, handler = menu[choice]
            if handler() == "exit":
                break
        else:
            print("That's not a valid option. Please try again.")



def files_menu(dm, user_id):
    files_manager = FilesManager(dm)
    
    print("\n" + "-" * 40)
    print("        Data Import Options")
    print("-" * 40)
    print("Add your receipts to start tracking spending.\n")
    
    menu = {
        "1": ("Enter a receipt manually", lambda: _persist_and_report(files_manager.upload_single_receipt(user_id), dm, user_id)),
        "2": ("Import a single file from data/raw", lambda: files_manager.select_one_from_raw(user_id)),
        "3": ("Import all files from data/raw", lambda: files_manager.select_all_from_raw(user_id)),
        "4": ("Clear all my saved data", lambda: _delete_user_data(dm, user_id)),
        "5": ("Go Back", lambda: "back"),
    }
    def _persist_and_report(txs, dm, user_id):
        if not txs:
            print("\nNo items were added.")
            return
        res = dm.add_transactions(user_id, txs)
        count = res.get('imported', 0)
        print(f"\nSuccess! Added {count} item(s) to your spending history.")
    def _delete_user_data(dm, user_id):
        print("\nWarning: This will permanently remove all your saved receipts.")
        confirm = input("Are you sure? Type 'yes' to confirm: ").strip().lower()
        if confirm == "yes":
            dm.delete_user_data(user_id, delete_upload_history=True)
            print("\nAll your data has been cleared. You can start fresh!")
        else:
            print("\nCancelled. Your data is safe.")
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
        recs, rec_file = llm_menu.load_recommendations(user_id)
        if not recs:
            print("\nNo saved recommendations found yet.")
            print("Try asking the AI for spending insights first!")
            return None

        # Group by category
        grouped = {}
        for r in recs:
            cat = r.get("category", "Uncategorized")
            grouped.setdefault(cat, []).append(r)

        categories = sorted(grouped.keys())
        total_count = len(recs)
        print("\n" + "=" * 50)
        print("     Your Saved Recommendations")
        print("=" * 50)
        print("\nSelect a category to view:\n")
        print(f"  0) View All ({total_count} recommendations)")
        for i, cat in enumerate(categories, 1):
            print(f"  {i}) {cat} ({len(grouped[cat])})")

        choice = input("\nEnter category number (default: all): ").strip() or "0"
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

    def delete_recommendations():
        return llm_menu.delete_recommendation(user_id)

    while True:
        has_data = dm.has_user_data(user_id)
        has_recs = llm_menu.has_recommendations(user_id)
        
        # Show personalized header based on data status
        print("\n" + "=" * 50)
        print(f"  Welcome back, {user_id}!")
        print("=" * 50)
        
        if not has_data:
            print("\nYou don't have any spending data yet.")
            print("Let's get started by importing your first receipts!\n")
            print("Tip: Choose 'Import Receipts' to add your spending data.")
        else:
            txs = dm.get_transactions_by_user(user_id)
            print(f"\nYou have {len(txs)} transactions on file.")
            if has_recs:
                print("You also have saved AI recommendations to review.\n")
            else:
                print("Try asking the AI for spending insights!\n")
        
        # Build menu dynamically based on available data
        menu_items = [("Import Receipts", files_option)]
        
        if has_data:
            menu_items.append(("Get AI Spending Insights", ask_llm))
            menu_items.append(("View My Reports & Recommendations", generate_reports))
            if has_recs:
                menu_items.append(("Manage Saved Recommendations", delete_recommendations))
            menu_items.append(("Browse My Transactions", transactions_option))
        
        menu_items.append(("Return to Main Menu", lambda: "back"))
        
        # Convert to numbered dict
        menu = {str(i): item for i, item in enumerate(menu_items, 1)}

        print("What would you like to do?")
        _show_menu(menu)
        choice = input("Enter your choice: ").strip()
        if choice in menu:
            _, handler = menu[choice]
            result = handler()
            if result == "back":
                break
        else:
            print("\nThat's not a valid option. Please select a number from the menu.")


def list_menu(dm, user_id):
    """Submenu for listing transactions, stores, receipts, and line items"""
    
    print("\n" + "-" * 40)
    print("      Transaction Explorer")
    print("-" * 40)
    print("View and browse your spending data.\n")
    
    def _safe_float(v):
        try:
            return float(v)
        except Exception:
            return 0.0

    # Get transactions once for checking what data exists
    txs = dm.get_transactions_by_user(user_id)
    
    # Check what data is available
    has_stores = any(t.get("store") for t in txs)
    has_receipts = any(t.get("orderno") or t.get("transaction_id") for t in txs)
    has_line_items = any(
        (t.get("item_name") or t.get("purchasedescription") or t.get("Description"))
        and str(t.get("item_name") or "").upper() != "RECEIPT_TOTAL"
        for t in txs
    )

    def show_transactions():
        nonlocal txs
        txs = dm.get_transactions_by_user(user_id)
        print(f"\nShowing {len(txs)} transactions (debug view):")
        for t in txs[:200]:
            print(t)
        return None

    def show_stores():
        txs = dm.get_transactions_by_user(user_id)
        store_pairs = [(t.get("store"), t.get("source")) for t in txs if t.get("store")]
        counts = Counter(store_pairs)
        print(f"\nYour Most Visited Stores:")
        print("-" * 30)
        for (store, source), cnt in counts.most_common(20):
            src = source or "unknown"
            print(f"  Store #{store} ({src}): {cnt} visits")
        show_all = input("\nShow complete store list? (y/N): ").strip().lower()
        if show_all == "y":
            print(f"\nAll Stores:")
            for (store, source), cnt in counts.items():
                src = source or "unknown"
                print(f"  Store #{store} ({src}): {cnt} visits")
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

        print(f"\nYour Receipts ({len(receipts)} total):")
        print("-" * 60)
        for rid, info in list(receipts.items())[:50]:
            store_src = f"Store #{info.get('store')} ({info.get('store_source') or 'unknown'})"
            print(f"  Receipt: {rid}")
            print(f"    Date: {info['date']} | {store_src} | {info['count']} items")
            print(f"    Subtotal: ${info['total_before']:.2f} | Final: ${info['total_after']:.2f}")
            print()

        print("Options:")
        print("  - Enter a receipt ID to see item details")
        print("  - Type 'a' to show all receipt details")
        print("  - Press Enter to go back")
        choice_detail = input("\nYour choice: ").strip()
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

        print(f"\nYour Purchased Items ({len(line_items)} total):")
        print("-" * 60)
        filter_rid = input("Filter by receipt ID (press Enter to see all): ").strip()
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
            print(f"  {it['name']}")
            print(f"    Receipt: {it['receipt']} | Store #{store} ({source or 'unknown'})")
            print(f"    Price: ${it['before']:.2f} | You Paid: ${it['after']:.2f}")
            print()
            shown += 1
            if shown >= 500:
                more = input("\nThere are more items. Continue viewing? (y/N): ").strip().lower()
                if more != "y":
                    break
                shown = 0
        if shown == 0:
            print("\nNo items found matching your criteria.")
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

    # Build menu dynamically based on available data
    menu_items = []
    if has_stores:
        menu_items.append(("View Stores Where You Shop", show_stores))
    if has_receipts:
        menu_items.append(("Browse Receipts by Date", show_receipts))
    if has_line_items:
        menu_items.append(("See All Purchased Items", show_line_items))
    menu_items.append(("Go Back", lambda: "back"))
    
    if len(menu_items) == 1:  # Only "Back" option
        print("\nNo spending data to display yet.")
        print("Import some receipts first to see your transaction history.")
        return
    
    menu = {str(i): item for i, item in enumerate(menu_items, 1)}

    _run_menu(menu)

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
