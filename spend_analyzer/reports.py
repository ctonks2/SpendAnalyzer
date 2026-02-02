"""Report generation and saving (simple CSV/text outputs)"""
import os
import csv


class ReportManager:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.join(os.getcwd(), "reports")
        os.makedirs(self.base_dir, exist_ok=True)

    def generate_report(self, name, data_manager, user_id):
        if name == "spending_by_store":
            return self._spending_by_store(data_manager, user_id)
        if name == "top_items":
            return self._top_items(data_manager, user_id)
        return None

    def _spending_by_store(self, dm, user_id):
        txs = dm.get_transactions_by_user(user_id)
        totals = {}
        for t in txs:
            store = t.get("store") or "Unknown"
            amt = t.get("total_price") or 0
            totals[store] = totals.get(store, 0) + (amt if isinstance(amt, (int, float)) else 0)
        rows = [(store, totals[store]) for store in sorted(totals, key=totals.get, reverse=True)]
        return {"name": "spending_by_store", "rows": rows}

    def _top_items(self, dm, user_id):
        txs = dm.get_transactions_by_user(user_id)
        counts = {}
        for t in txs:
            item = t.get("item_name") or "Unknown"
            amt = t.get("total_price") or 0
            counts[item] = counts.get(item, 0) + (amt if isinstance(amt, (int, float)) else 0)
        rows = [(item, counts[item]) for item in sorted(counts, key=counts.get, reverse=True)]
        return {"name": "top_items", "rows": rows}

    def save_report(self, report, user_id, report_name=None):
        user_dir = os.path.join(self.base_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        filename = f"{report_name or report.get('name', 'report')}.csv"
        path = os.path.join(user_dir, filename)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["key", "value"])
            for k, v in report.get("rows", []):
                writer.writerow([k, v])
        return path
