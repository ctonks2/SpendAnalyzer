from datetime import datetime
import os

class FilesManager:
    def __init__(self, dm):
        self.dm = dm

    def upload_single_receipt(self, user_id):
        print("\nManual receipt entry")
        while True:
            store_number = input("Enter store number (required): ").strip()
            if store_number:
                break
            print("Store number required. Please enter a numeric or alphanumeric store id.")
        store_name = input("Enter store/location name: ").strip() or "unknown"
        date_iso = self._prompt_date()
        orderno = f"{store_number}.{date_iso}"
        items = []
        while True:
            name = input("Item name (blank to finish): ").strip()
            if not name:
                if items:
                    break
                print("Please enter at least one item.")
                continue
            while True:
                p = input("  Unit price: ").strip()
                try:
                    unit_price = float(p)
                    break
                except Exception:
                    print("  Enter a numeric price (e.g. 3.49)")
            d = input("  Discount amount (enter for 0): ").strip()
            try:
                discount = float(d) if d else 0.0
            except Exception:
                discount = 0.0
            q = input("  Quantity (default 1): ").strip()
            try:
                qty = float(q) if q else 1.0
            except Exception:
                qty = 1.0
            upc = input("  UPC (optional): ").strip() or None
            total_before = unit_price * qty
            total_after = max(0.0, total_before - discount)
            row = {
                "user_id": user_id,
                "item_name": name,
                "unit_price": unit_price,
                "qty": qty,
                "discount": discount,
                "total_before": round(total_before, 2),
                "total_after": round(total_after, 2),
                "upc": upc,
                "store": store_number,
                "source": store_name,
                "date": date_iso,
                "orderno": orderno,
            }
            if hasattr(self.dm, "_normalize_row"):
                try:
                    row = self.dm._normalize_row(row, user_id)
                except Exception:
                    pass
            items.append(row)
            more = input("Add another item? (Y/n): ").strip().lower()
            if more == "n":
                break
        total_after = round(sum(r.get("total_after", 0.0) for r in items), 2)
        receipt_row = {
            "user_id": user_id,
            "item_name": "RECEIPT_TOTAL",
            "unit_price": 0.0,
            "qty": 1.0,
            "discount": 0.0,
            "total_before": 0.0,
            "total_after": total_after,
            "upc": None,
            "store": store_number,
            "source": store_name,
            "date": date_iso,
            "orderno": orderno,
        }
        if hasattr(self.dm, "_normalize_row"):
            try:
                receipt_row = self.dm._normalize_row(receipt_row, user_id)
            except Exception:
                pass
        return items + [receipt_row]

    def _prompt_date(self, prompt="Enter date (YYYY-MM-DD) [today]: "):
        s = input(prompt).strip()
        if not s:
            return datetime.today().date().isoformat()
        try:
            return datetime.fromisoformat(s).date().isoformat()
        except Exception:
            try:
                return datetime.strptime(s, "%m/%d/%Y").date().isoformat()
            except Exception:
                return datetime.today().date().isoformat()

    def select_one_from_raw(self, user_id):
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
                    result = self.dm.import_file(selected_file, user_id)
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

    def select_all_from_raw(self, user_id):
        results = self.dm.import_all_from_raw(user_id)
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
