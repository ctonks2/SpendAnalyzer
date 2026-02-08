"""Simple CLI for Spend Analyzer prototype"""
import os
import json
from collections import Counter, defaultdict
from .data_manager import DataManager
from .llm_client import LLMClient
from .reports import ReportManager


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
    rm = ReportManager()

    print("Welcome to Spend Analyzer (CLI Prototype)")

    def role_user():
        user_id = input("Enter your user id (e.g., alice): ").strip() or "user"
        user_menu(dm, llm, rm, user_id)
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


def _get_duplicate_handling():
    """Ask user how to handle duplicates"""
    print("\nHow to handle duplicates?")
    print("1) Skip (don't import duplicates)")
    print("2) Replace (overwrite existing transactions)")
    print("3) Allow (import anyway)")
    choice = input("Choice (default: 1): ").strip() or "1"
    if choice == "1":
        return "skip"
    elif choice == "2":
        return "replace"
    elif choice == "3":
        return "allow"
    else:
        print("Invalid choice, using 'skip'")
        return "skip"


def files_menu(dm, user_id):
    """Submenu for managing files"""

    def upload_by_path():
        path = input("Path to file: ").strip()
        try:
            duplicate_handling = _get_duplicate_handling()
            result = dm.import_file(path, user_id, duplicate_handling=duplicate_handling)
            imported = result.get("imported", 0)
            skipped = result.get("skipped", 0)
            replaced = result.get("replaced", 0)
            print(f"Imported {imported}, Skipped {skipped}, Replaced {replaced} for user {user_id}.")
        except Exception as e:
            print("Error importing file:", e)
        return None

    def select_one_from_raw():
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        if not os.path.exists(raw_dir):
            print("data/raw/ directory does not exist.")
            return None
        
        files = [f for f in os.listdir(raw_dir) if os.path.isfile(os.path.join(raw_dir, f))]
        if not files:
            print("No files found in data/raw/")
            return None
        
        print("\nFiles in data/raw/:")
        for i, fname in enumerate(files, 1):
            print(f"{i}) {fname}")
        
        choice = input("Select file number: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                selected_file = os.path.join(raw_dir, files[idx])
                try:
                    duplicate_handling = _get_duplicate_handling()
                    result = dm.import_file(selected_file, user_id, duplicate_handling=duplicate_handling)
                    imported = result.get("imported", 0)
                    skipped = result.get("skipped", 0)
                    replaced = result.get("replaced", 0)
                    print(f"Imported {imported}, Skipped {skipped}, Replaced {replaced} from {files[idx]}.")
                except Exception as e:
                    print(f"Error importing {files[idx]}:", e)
            else:
                print("Invalid selection.")
        except ValueError:
            print("Invalid input.")
        return None

    def select_all_from_raw():
        duplicate_handling = _get_duplicate_handling()
        results = dm.import_all_from_raw(user_id, duplicate_handling=duplicate_handling)
        if not results:
            print("No files found in data/raw/")
            return None
        print("\nImport results:")
        total_imported = 0
        total_skipped = 0
        total_replaced = 0
        for fname, res in results.items():
            if isinstance(res, dict):
                imported = res.get("imported", 0)
                skipped = res.get("skipped", 0)
                replaced = res.get("replaced", 0)
                total_imported += imported
                total_skipped += skipped
                total_replaced += replaced
                print(f"{fname}: imported={imported}, skipped={skipped}, replaced={replaced}")
            else:
                print(f"{fname}: {res}")
        print(f"\nTotal: imported={total_imported}, skipped={total_skipped}, replaced={total_replaced}")
        return None

    menu = {
        "1": ("Give a file path", upload_by_path),
        "2": ("Select one from raw data", select_one_from_raw),
        "3": ("Select all from raw data", select_all_from_raw),
        "4": ("Back", lambda: "back"),
    }

    _run_menu(menu)


def user_menu(dm, llm, rm, user_id):
    """User menu with main options"""

    def files_option():
        files_menu(dm, user_id)
        return None

    def ask_llm():
        print("Entering LLM chat. Type 'exit' or 'back' to return to the menu.")
        messages = []
        context = dm.get_transactions_by_user(user_id)
        context_included = False
        
        while True:
            try:
                q = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            if q.lower() in ("exit", "back", "quit"):
                break

            # Include transaction context in the first message if using an agent
            if not context_included and getattr(llm, "agent_id", None) and context:
                ctx_snippet = json.dumps(context[:200], default=str)
                full_content = f"Context (my transactions):\n{ctx_snippet}\n\nMy question:\n{q}"
                context_included = True
            else:
                full_content = q
            
            # Add user message
            messages.append({"role": "user", "content": full_content})

            # If an agent is configured, use the agent conversations endpoint with full message history
            if getattr(llm, "agent_id", None):
                res = llm.start_agent_conversation(inputs=messages)
                # Handle error dicts
                if isinstance(res, dict) and res.get("error"):
                    body = res.get("body")
                    print("Agent error:", res.get("error"), "", body if body else "")
                    # Do not append assistant message on error
                    continue

                # Try to extract assistant text from common response shapes
                assistant_text = None
                if isinstance(res, dict):
                    if "outputs" in res and isinstance(res["outputs"], list) and res["outputs"]:
                        out = res["outputs"][0]
                        # content may be a string or list
                        content = out.get("content") if isinstance(out, dict) else None
                        if isinstance(content, list):
                            texts = [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
                            assistant_text = "\n".join(t for t in texts if t)
                        elif isinstance(content, str):
                            assistant_text = content
                    elif "results" in res and isinstance(res["results"], list) and res["results"]:
                        first = res["results"][0]
                        contents = first.get("content") or []
                        if isinstance(contents, list):
                            texts = [c.get("text") for c in contents if isinstance(c, dict) and c.get("text")]
                            assistant_text = "\n".join(t for t in texts if t)
                        elif isinstance(contents, str):
                            assistant_text = contents

                if assistant_text is None:
                    # Fallback to stringifying the whole response
                    try:
                        assistant_text = json.dumps(res)
                    except Exception:
                        assistant_text = str(res)

                print("Assistant:", assistant_text)
                messages.append({"role": "assistant", "content": assistant_text})
            else:
                # Non-agent flow uses llm.ask which can accept a context list of transactions
                context = dm.get_transactions_by_user(user_id)
                resp = llm.ask(q, context=context)
                print("Assistant:\n", resp)

        return None

    def generate_reports():
        print("Available reports: 1) spending_by_store 2) top_items")
        r = input("Choose report: ")
        report = rm.generate_report(r, dm, user_id)
        if report:
            path = rm.save_report(report, user_id, r)
            print(f"Report saved to {path}")
        else:
            print("Unknown report")
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
        print(f"Transactions ({len(txs)})")
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
            "line_items": [], "total_before": 0.0, "total_after": 0.0
        })

        for t in txs:
            rid = t.get(grouping_field) or t.get("transaction_id")
            receipts[rid]["count"] += 1
            receipts[rid]["store"] = receipts[rid]["store"] or t.get("store")
            receipts[rid]["store_source"] = receipts[rid].get("store_source") or t.get("source")
            receipts[rid]["date"] = receipts[rid]["date"] or t.get("date")

            qty = _safe_float(t.get("quantity") or 1)
            unit = _safe_float(t.get("unit_price") or t.get("retailamt") or 0)
            total = _safe_float(t.get("total_price") or t.get("customerloyamt") or 
                              t.get("TransPrice") or (unit * qty))

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
                          f"total={li['total']:.2f} store={li.get('store')} (source={li.get('store_source')})")
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
                          f"total={li['total']:.2f} store={li.get('store')} (source={li.get('store_source')})")
            else:
                print("Receipt id not found in the current user's data.")
        return None

    def show_line_items():
        txs = dm.get_transactions_by_user(user_id)
        line_items = []
        for t in txs:
            name = t.get("item_name") or t.get("purchasedescription") or t.get("Description")
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
        "1": ("Transactions (raw upload)", show_transactions),
        "2": ("Common stores (in-memory)", show_stores),
        "3": ("Receipts summary (grouped by orderno)", show_receipts),
        "4": ("Line items summary (top products)", show_line_items),
        "5": ("Show DB stores/receipts/line_items (if DB available)", show_db),
        "6": ("Back", lambda: "back"),
    }

    _run_menu(menu)


def admin_menu(dm, llm, rm):
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
