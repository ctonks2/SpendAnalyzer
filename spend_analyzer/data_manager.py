"""Data manager for in-memory storage and import/normalization"""
import csv
import json
import os
import re
from datetime import datetime
import yaml
import pandas as pd
from PyPDF2 import PdfReader

DEFAULT_MAPPING = {
    "date": ["date", "purchase_date", "transaction_date", "Date"],
    "store": ["store", "merchant", "location", "Store"],
    "item_name": ["item", "name", "description", "purchasedescription", "Description"],
    "quantity": ["qty", "quantity", "amount", "Quantity"],
    "unit_price": ["price", "unit_price", "retailamt", "Price"],
    "total_price": ["total", "total_price", "amount", "customerloyamt", "TransPrice", "GrandTotal"],
    "category": ["category", "cat", "product_category"],
    # Additional helpful fields
    "orderno": ["orderno", "Trans", "trans"],
    "product_upc": ["productupc", "UPC", "upc"],
}


def _load_mappings():
    cfg = {}
    cfg_path = os.path.join(os.getcwd(), "configs", "store_mappings.yaml")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        except Exception:
            cfg = {}
    return cfg


class DataManager:
    def __init__(self):
        self.transactions = []  # list of dicts
        self.mappings = _load_mappings()

    def import_file(self, path, user_id="user"):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        _, ext = os.path.splitext(path)
        if ext.lower() in (".csv",):
            return self._import_csv(path, user_id)
        elif ext.lower() in (".json",):
            return self._import_json(path, user_id)
        elif ext.lower() in (".xlsx", ".xls"):
            return self._import_xlsx(path, user_id)
        elif ext.lower() in (".pdf",):
            return self._import_pdf(path, user_id)
        else:
            raise ValueError("Unsupported file type")

    def _import_csv(self, path, user_id):
        count = 0
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                tx = self._normalize_row(row, user_id)
                self.transactions.append(tx)
                count += 1
        return count

    def _collect_items_from_data(self, data):
        """Recursively collect all item dictionaries found under any 'items' key."""
        found = []
        def walk(obj, parent=None):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == 'items' and isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                merged = dict(item)
                                # inherit some useful parent fields if present
                                for field in ('date', 'purchase_date', 'orderno', 'store', 'time'):
                                    if field in obj and field not in merged:
                                        merged[field] = obj[field]
                                found.append(merged)
                            else:
                                found.append(item)
                    else:
                        walk(v, obj)
            elif isinstance(obj, list):
                for el in obj:
                    walk(el, parent)
        walk(data)
        return found

    def _import_json(self, path, user_id):
        """Import JSON with some tolerance for common formatting issues (trailing commas, comments)."""
        count = 0
        with open(path, encoding="utf-8") as fh:
            text = fh.read()

        # Try standard JSON parsing first
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            # Attempt simple fixes: remove // comments, /* */ comments, and trailing commas
            cleaned = re.sub(r"//.*?$", "", text, flags=re.M)
            cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.S)
            cleaned = re.sub(r",\s*(\]|})", r"\1", cleaned)
            data = None
            try:
                data = json.loads(cleaned)
            except Exception:
                # Second-pass: remove standalone numeric artifacts (e.g., page numbers or stray digits)
                cleaned2 = re.sub(r"^\s*\d+\s*,?\s*$", "", cleaned, flags=re.M)
                # Try cleaned2 first
                try:
                    data = json.loads(cleaned2)
                except Exception:
                    # Also try to extract the first JSON-like substring as a last resort
                    m = re.search(r"(\{.*\}|\[.*\])", cleaned2, re.S)
                    if m:
                        try:
                            candidate = m.group(1)
                            data = json.loads(candidate)
                        except Exception:
                            data = None
                if data is None:
                    raise ValueError(f"JSON parse error: {e}; attempted fixes failed")

        # Normalize: collect item dicts from nested structures
        items = []
        if isinstance(data, dict):
            # collect items under any nested 'items' key
            items = self._collect_items_from_data(data)
            # if no nested items found but top-level 'items' exists, use that
            if not items and 'items' in data:
                items = data['items']
            # if still no items, fall back to treating the dict as a single record
            if not items:
                items = [data]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]

        for row in items:
            tx = self._normalize_row(row, user_id)
            self.transactions.append(tx)
            count += 1
        return count

    def _import_xlsx(self, path, user_id):
        """Import an XLSX where each row is an item. Rows with an isTotalline flag mark receipt totals."""
        # Read the default sheet; if expected Macey columns aren't present, try sheet index 1 (sheet2)
        df = pd.read_excel(path, engine="openpyxl")
        # If the sheet doesn't include typical Macey columns, attempt to read sheet2
        if not any(c in df.columns for c in ("UPC", "Description", "Trans", "Price", "TransPrice")):
            try:
                df = pd.read_excel(path, sheet_name=1, engine="openpyxl")
            except Exception:
                pass
        count = 0
        for _, row in df.fillna("").iterrows():
            # convert pandas Series to plain dict with string keys
            rowdict = {str(k): (None if pd.isna(v) else v) for k, v in row.items()}
            # check for total line markers
            is_total = False
            for key in ("isTotalline", "isTotalLine", "is_total_line", "is_total"):
                if key in rowdict and str(rowdict.get(key)).strip() in ("1", "True", "true", "Y", "y"):
                    is_total = True
                    break
            if is_total:
                # create a receipt-level transaction
                tx = {
                    "transaction_id": f"tx_{len(self.transactions)+1}",
                    "user_id": user_id,
                    "date": rowdict.get("date") or rowdict.get("purchase_date"),
                    "store": rowdict.get("store") or rowdict.get("merchant"),
                    "item_name": "RECEIPT_TOTAL",
                    "quantity": 1,
                    "unit_price": None,
                    "total_price": rowdict.get("total") or rowdict.get("amount") or rowdict.get("price"),
                    "category": None,
                }
                # Require a present, numeric total_price for receipt-level transactions; otherwise skip
                tp = tx.get("total_price")
                if tp in (None, ""):
                    # skip adding empty receipt totals
                    continue
                try:
                    tx["total_price"] = float(str(tp).replace(",", ""))
                except Exception:
                    # if conversion fails, skip this receipt total
                    continue
                self.transactions.append(tx)
                count += 1
            else:
                tx = self._normalize_row(rowdict, user_id)
                self.transactions.append(tx)
                count += 1
        return count

    def _import_pdf(self, path, user_id):
        """Attempt to extract text from a PDF and parse a JSON blob if present."""
        count = 0
        reader = PdfReader(path)
        text = []
        for p in reader.pages:
            try:
                text.append(p.extract_text() or "")
            except Exception:
                text.append("")
        full = "\n".join(text).strip()
        # try to find JSON structures
        # direct parse
        try:
            data = json.loads(full)
        except Exception:
            # search for first {...} or [...]
            m = re.search(r"(\{.*\}|\[.*\])", full, re.S)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    data = None
            else:
                data = None
        if data is None:
            raise ValueError("No JSON found in PDF")
        # reuse the JSON import logic by writing to a temp variable
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]
        for row in items:
            tx = self._normalize_row(row, user_id)
            self.transactions.append(tx)
            count += 1
        return count

    def import_all_from_raw(self, user_id="user"):
        """Import all files found in data/raw and return summary dict"""
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        results = {}
        if not os.path.exists(raw_dir):
            return results
        for fname in os.listdir(raw_dir):
            path = os.path.join(raw_dir, fname)
            if os.path.isfile(path):
                try:
                    cnt = self.import_file(path, user_id)
                    results[fname] = cnt
                except Exception as e:
                    results[fname] = f"error: {e}"
        return results

    def _normalize_row(self, row, user_id):
        # Row is a mapping of arbitrary keys -> values.
        normalized = {
            "transaction_id": f"tx_{len(self.transactions)+1}",
            "user_id": user_id,
            "date": None,
            "store": None,
            "item_name": None,
            "quantity": 1,
            "unit_price": None,
            "total_price": None,
            "category": None,
            "orderno": None,
            "product_upc": None,
        }
        # simple key matching using DEFAULT_MAPPING
        for canon, candidates in DEFAULT_MAPPING.items():
            for cand in candidates:
                if cand in row and row[cand] not in (None, ""):
                    normalized[canon if canon != "total_price" else "total_price"] = row[cand]
                    break
        # Coping with common keys
        if normalized["total_price"] in (None, "") and "amount" in row:
            normalized["total_price"] = row.get("amount")

        # Ensure ordner/product_upc values are strings when present
        if normalized.get("orderno") not in (None, ""):
            normalized["orderno"] = str(normalized.get("orderno"))
        if normalized.get("product_upc") not in (None, ""):
            normalized["product_upc"] = str(normalized.get("product_upc"))

        # Attempt to parse date
        d = normalized.get("date") or row.get("date") or row.get("purchase_date")
        if d:
            try:
                dt = datetime.fromisoformat(d)
                # If time is midnight, prefer date-only string (YYYY-MM-DD)
                if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                    normalized["date"] = dt.date().isoformat()
                else:
                    normalized["date"] = dt.isoformat()
            except Exception:
                normalized["date"] = str(d)

        # Capture order/receipt id if available
        if not normalized.get("orderno"):
            if "orderno" in row and row.get("orderno") not in (None, ""):
                normalized["orderno"] = str(row.get("orderno"))
            elif "Trans" in row and row.get("Trans") not in (None, ""):
                normalized["orderno"] = str(row.get("Trans"))
            elif "trans" in row and row.get("trans") not in (None, ""):
                normalized["orderno"] = str(row.get("trans"))

        # Capture UPC/product identifier if present
        if not normalized.get("product_upc"):
            if "productupc" in row and row.get("productupc") not in (None, ""):
                normalized["product_upc"] = str(row.get("productupc"))
            elif "UPC" in row and row.get("UPC") not in (None, ""):
                normalized["product_upc"] = str(row.get("UPC"))

        # Prefer retailamt as unit_price (pre-discount) and customerloyamt/TransPrice as total_price (post-discount)
        if normalized.get("unit_price") in (None, ""):
            if "retailamt" in row and row.get("retailamt") not in (None, ""):
                normalized["unit_price"] = row.get("retailamt")
            elif "Price" in row and row.get("Price") not in (None, ""):
                normalized["unit_price"] = row.get("Price")

        if normalized.get("total_price") in (None, ""):
            if "customerloyamt" in row and row.get("customerloyamt") not in (None, ""):
                normalized["total_price"] = row.get("customerloyamt")
            elif "TransPrice" in row and row.get("TransPrice") not in (None, ""):
                normalized["total_price"] = row.get("TransPrice")
            elif "GrandTotal" in row and row.get("GrandTotal") not in (None, ""):
                normalized["total_price"] = row.get("GrandTotal")

        # numeric conversions
        try:
            if normalized.get("quantity") is not None:
                normalized["quantity"] = float(normalized.get("quantity"))
        except Exception:
            normalized["quantity"] = 1
        try:
            if normalized.get("unit_price") not in (None, ""):
                normalized["unit_price"] = float(normalized.get("unit_price"))
        except Exception:
            pass
        try:
            if normalized.get("total_price") not in (None, ""):
                normalized["total_price"] = float(normalized.get("total_price"))
        except Exception:
            pass

        return normalized

    def get_transactions_by_user(self, user_id):
        return [t for t in self.transactions if t.get("user_id") == user_id]
