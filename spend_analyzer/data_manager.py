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
    "date": ["date", "purchase_date", "transaction_date"],
    "store": ["store", "merchant", "location"],
    "item_name": ["item", "name", "description"],
    "quantity": ["qty", "quantity", "amount"],
    "unit_price": ["price", "unit_price"],
    "total_price": ["total", "total_price", "amount"],
    "category": ["category", "cat"],
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

    def _import_json(self, path, user_id):
        count = 0
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
            # Expect list of items or dict with 'items'
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

    def _import_xlsx(self, path, user_id):
        """Import an XLSX where each row is an item. Rows with an isTotalline flag mark receipt totals."""
        df = pd.read_excel(path, engine="openpyxl")
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
                # attempt numeric conversion
                try:
                    if tx["total_price"] not in (None, ""):
                        tx["total_price"] = float(str(tx["total_price"]).replace(",", ""))
                except Exception:
                    pass
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

        # Attempt to parse date
        d = normalized.get("date") or row.get("date") or row.get("purchase_date")
        if d:
            try:
                normalized["date"] = str(datetime.fromisoformat(d))
            except Exception:
                normalized["date"] = str(d)

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

        # Attempt to parse date
        d = normalized.get("date") or row.get("date") or row.get("purchase_date")
        if d:
            try:
                normalized["date"] = str(datetime.fromisoformat(d))
            except Exception:
                normalized["date"] = str(d)

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
