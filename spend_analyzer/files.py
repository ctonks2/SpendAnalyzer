from datetime import datetime
import os
import re


def _validate_date(value):
    """Validate and parse date. Returns ISO date string or None."""
    if not value:
        return None
    value = str(value).strip()
    # Try ISO format first
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except Exception:
        pass
    # Try MM/DD/YYYY
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except Exception:
        pass
    # Try MM-DD-YYYY
    try:
        return datetime.strptime(value, "%m-%d-%Y").date().isoformat()
    except Exception:
        pass
    return None


def _validate_string(value, field_name, required=False):
    """Validate string value. Returns string or None."""
    if value is None or str(value).strip() == "":
        if required:
            raise ValueError(f"{field_name} is required and must be a non-empty string.")
        return None
    return str(value).strip()


def _validate_number(value, field_name, required=False, allow_negative=False):
    """Validate numeric value. Returns float or None."""
    if value is None or str(value).strip() == "":
        if required:
            raise ValueError(f"{field_name} is required and must be a number.")
        return None
    try:
        num = float(value)
        if not allow_negative and num < 0:
            raise ValueError(f"{field_name} cannot be negative.")
        return num
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be a valid number.")


def _validate_upc(value):
    """Validate UPC as a number. Returns int or None."""
    if value is None or str(value).strip() == "":
        return None
    # Remove any non-digit characters
    digits = re.sub(r'\D', '', str(value))
    if not digits:
        raise ValueError("UPC must contain numeric digits.")
    try:
        return int(digits)
    except (ValueError, TypeError):
        raise ValueError("UPC must be a valid number.")


class FilesManager:
    def __init__(self, dm):
        self.dm = dm

    def _print_upload_history(self, user_id):
        names = self.dm.get_uploaded_filenames(user_id)
        if not names:
            print("\nNo files have been uploaded yet.")
            return []
        print("\nYour previously uploaded files:")
        for name in names:
            print(f"  - {name}")
        return names

    def upload_single_receipt(self, user_id):
        print("\n" + "=" * 50)
        print("      Manual Receipt Entry")
        print("=" * 50)
        print("\nEnter your receipt details below.")
        print("We'll guide you through each field.\n")
        print("Field Requirements:")
        print("  Date      - Format: YYYY-MM-DD (e.g., 2026-02-17)")
        print("  Store     - Store number or identifier")
        print("  Item name - Name of the product")
        print("  Quantity  - How many purchased (number)")
        print("  Price     - Cost per item (number)")
        print("  Category  - Product category (optional)")
        print("  UPC       - Barcode number (optional)")
        print("\n" + "-" * 50)
        
        # Store number validation (string, required)
        while True:
            store_input = input("\nStore number or ID: ").strip()
            try:
                store_number = _validate_string(store_input, "Store number", required=True)
                break
            except ValueError as e:
                print(f"  Oops! {e}")
        
        # Store name validation (string, optional)
        store_name_input = input("Store name (e.g., Walmart, Target): ").strip()
        store_name = _validate_string(store_name_input, "Store name") or "unknown"
        
        # Date validation
        while True:
            date_input = input("Purchase date (YYYY-MM-DD) [press Enter for today]: ").strip()
            if not date_input:
                date_iso = datetime.today().date().isoformat()
                print(f"  Using today's date: {date_iso}")
                break
            date_iso = _validate_date(date_input)
            if date_iso:
                break
            print("  Invalid date format. Try YYYY-MM-DD (e.g., 2026-02-17)")
        
        orderno = f"{store_number}.{date_iso}"
        items = []
        print("\n" + "-" * 50)
        print("Now let's add the items you purchased.")
        print("-" * 50)
        
        while True:
            # Item name validation (string, required for each item)
            item_num = len(items) + 1
            name_input = input(f"\nItem #{item_num} name (press Enter when done): ").strip()
            if not name_input:
                if items:
                    break
                print("Please add at least one item to your receipt.")
                continue
            try:
                name = _validate_string(name_input, "Item name", required=True)
            except ValueError as e:
                print(f"  Oops! {e}")
                continue
            
            # Unit price validation (number, required)
            while True:
                p = input("  Price per unit: $").strip()
                try:
                    unit_price = _validate_number(p, "Unit price", required=True)
                    break
                except ValueError as e:
                    print(f"    {e}")
            
            # Discount validation (number, optional)
            while True:
                d = input("  Discount amount (press Enter for none): $").strip()
                try:
                    discount = _validate_number(d, "Discount", allow_negative=False) or 0.0
                    break
                except ValueError as e:
                    print(f"    {e}")
            
            # Quantity validation (number, optional, default 1)
            while True:
                q = input("  Quantity purchased (default: 1): ").strip()
                try:
                    qty = _validate_number(q, "Quantity") if q else 1.0
                    if qty is None:
                        qty = 1.0
                    break
                except ValueError as e:
                    print(f"    {e}")
            
            # Category validation (string, optional)
            category_input = input("  Category (e.g., Groceries, Electronics): ").strip()
            category = _validate_string(category_input, "Category") or None
            
            # UPC validation (number, optional)
            while True:
                upc_input = input("  UPC barcode (press Enter to skip): ").strip()
                if not upc_input:
                    upc = None
                    break
                try:
                    upc = _validate_upc(upc_input)
                    break
                except ValueError as e:
                    print(f"    {e}")
            
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
                "category": category,
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
            print(f"  >> Added: {name} - ${total_after:.2f}")
            more = input("\nAdd another item? (Y/n): ").strip().lower()
            if more == "n":
                break
        
        total_after = round(sum(r.get("total_after", 0.0) for r in items), 2)
        
        # Show summary
        print("\n" + "=" * 50)
        print("       Receipt Summary")
        print("=" * 50)
        print(f"  Store: {store_name} (#{store_number})")
        print(f"  Date: {date_iso}")
        print(f"  Items: {len(items)}")
        print(f"  Total: ${total_after:.2f}")
        print("=" * 50)
        
        receipt_row = {
            "user_id": user_id,
            "item_name": "RECEIPT_TOTAL",
            "unit_price": 0.0,
            "qty": 1.0,
            "discount": 0.0,
            "total_before": 0.0,
            "total_after": total_after,
            "upc": None,
            "category": None,
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
        self._print_upload_history(user_id)
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        if not os.path.exists(raw_dir):
            print("\nThe data/raw folder doesn't exist yet.")
            print("Place your receipt files there to import them.")
            return None
        files = [f for f in os.listdir(raw_dir) if os.path.isfile(os.path.join(raw_dir, f))]
        if not files:
            print("\nNo files found in data/raw/")
            print("Add some receipt files (CSV, JSON, XLSX) to import.")
            return None
        print("\nAvailable files to import:")
        print("-" * 30)
        for i, fname in enumerate(files, 1):
            print(f"  {i}) {fname}")
        choice = input("\nEnter file number to import: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                selected_name = files[idx]
                existing = self.dm.get_uploaded_filenames(user_id)
                if selected_name in existing:
                    print("\nYou've already imported that file. Choose a different one.")
                    return None
                selected_file = os.path.join(raw_dir, selected_name)
                try:
                    result = self.dm.import_file(selected_file, user_id)
                    imported = result.get("imported", 0)
                    skipped = result.get("skipped", 0)
                    replaced = result.get("replaced", 0)
                    self.dm.save_user_data(user_id)
                    self.dm.add_uploaded_filename(user_id, selected_name)
                    print(f"\nSuccess! Imported {imported} items from {selected_name}")
                    if skipped > 0:
                        print(f"  ({skipped} duplicates skipped)")
                except Exception as e:
                    print(f"\nCouldn't import {selected_name}: {e}")
            else:
                print("\nThat's not a valid file number.")
        except ValueError:
            print("\nPlease enter a number.")
        return None

    def select_all_from_raw(self, user_id):
        self._print_upload_history(user_id)
        existing = set(self.dm.get_uploaded_filenames(user_id))
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        if not os.path.exists(raw_dir):
            print("\nThe data/raw folder doesn't exist yet.")
            print("Place your receipt files there to import them.")
            return None
        results = {}
        print("\nImporting all new files from data/raw/...")
        for fname in os.listdir(raw_dir):
            path = os.path.join(raw_dir, fname)
            if not os.path.isfile(path):
                continue
            if fname in existing:
                results[fname] = "already imported"
                continue
            try:
                res = self.dm.import_file(path, user_id)
                self.dm.save_user_data(user_id)
                self.dm.add_uploaded_filename(user_id, fname)
                results[fname] = res
            except Exception as e:
                results[fname] = f"error: {e}"
        if not results:
            print("\nNo files found in data/raw/")
            print("Add some receipt files (CSV, JSON, XLSX) to import.")
            return None
        print("\n" + "=" * 50)
        print("       Import Results")
        print("=" * 50)
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
                print(f"  {fname}: {imported} items imported")
                if skipped > 0:
                    print(f"    ({skipped} duplicates skipped)")
            else:
                print(f"  {fname}: {res}")
        print("-" * 50)
        print(f"  Total items imported: {total_imported}")
        if total_skipped > 0:
            print(f"  Duplicates skipped: {total_skipped}")
        print("=" * 50)
        return None
