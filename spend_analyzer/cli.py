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
        1) Upload a file (CSV or JSON)
        2) Ask the LLM about my spending
        3) Generate a list of premade reports
        4) List my transactions (in-memory)
        5) Back
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
            txs = dm.get_transactions_by_user(user_id)
            print(f"Transactions ({len(txs)})")
            for t in txs[:20]:
                print(t)
        elif choice == "5":
            break
        else:
            print("Invalid choice.")


def admin_menu(dm, llm, rm):
    while True:
        print(textwrap.dedent("""
        \nAdmin Menu:
        1) View all transactions
        2) Ask the LLM (admin-wide)
        3) Define a new premade report (prompt LLM for ideas)
        4) Back
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
            break
        else:
            print("Invalid choice.")
