"""Data manager for in-memory storage and import/normalization"""
import csv
import json
import os
import re
from datetime import datetime
import yaml
import pandas as pd
from PyPDF2 import PdfReader
import shutil
import tempfile

DEFAULT_MAPPING = {
    "date": ["date", "purchase_date", "transaction_date", "Date"],
    "store": ["store", "merchant", "location", "Store", "Whs"],
    "item_name": ["item", "name", "description", "purchasedescription", "Description","Item Description"],
    "quantity": ["qty","Qty", "quantity", "amount", "Quantity"],
    "unit_price": ["price", "unit_price", "retailamt", "Price"],
    "total_price": ["total", "total_price", "amount", "Amount", "customerloyamt", "TransPrice", "GrandTotal"],
    "category": ["category", "cat", "product_category"],
    # Additional helpful fields
    "orderno": ["orderno", "Trans", "trans"],
    "product_upc": ["productupc", "UPC", "upc","Item"],
}


def _get_project_root():
    """Get the project root directory"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _load_mappings():
    cfg = {}
    project_root = _get_project_root()
    cfg_path = os.path.join(project_root, "configs", "store_mappings.yaml")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        except Exception:
            cfg = {}
    return cfg


def _infer_source_from_filename(path):
    """Infer the file source name from the filename. Returns a cleaned first token, e.g., 'Smiths' or 'Maceys'."""
    try:
        base = os.path.basename(path)
        name = os.path.splitext(base)[0]
        # Split on underscore or space, take first chunk
        first = name.split("_")[0].split(" ")[0]
        # remove punctuation like apostrophes, keep alnum
        cleaned = "".join(ch for ch in first if ch.isalnum())
        return cleaned.title() if cleaned else name
    except Exception:
        return path


def _extract_date_from_filename(path):
    """Extract date from filename in YYYYMMDD format.
    
    Returns the date as an ISO string (YYYY-MM-DD) or None if no date found.
    Example: 'Smiths_20250423.json' -> '2025-04-23'
    """
    try:
        base = os.path.basename(path)
        name = os.path.splitext(base)[0]
        # Look for YYYYMMDD pattern (8 consecutive digits)
        match = re.search(r'(\d{8})', name)
        if match:
            date_str = match.group(1)
            # Parse as YYYYMMDD
            year = date_str[0:4]
            month = date_str[4:6]
            day = date_str[6:8]
            return f"{year}-{month}-{day}"
    except Exception:
        pass
    return None


def _get_cutoff_date_for_file(file_path, raw_dir):
    """Get the cutoff date for importing a specific file.
    
    If there are other files from the same store with earlier dates,
    returns the earliest date from those files. Otherwise returns None.
    
    This prevents re-importing old data when importing newer receipt files.
    """
    try:
        # Extract store name and current file's date
        source = _infer_source_from_filename(file_path)
        file_date = _extract_date_from_filename(file_path)
        
        if not source or not file_date:
            return None
        
        # Find all other files from the same store with dates
        all_files = []
        if os.path.exists(raw_dir):
            for fname in os.listdir(raw_dir):
                fpath = os.path.join(raw_dir, fname)
                if os.path.isfile(fpath) and fname != os.path.basename(file_path):
                    other_source = _infer_source_from_filename(fpath)
                    other_date = _extract_date_from_filename(fpath)
                    if other_source == source and other_date:
                        all_files.append((other_date, fname))
        
        # Find the maximum date from files older than the current file
        cutoff_dates = [d for d, _ in all_files if d < file_date]
        if cutoff_dates:
            # Return the maximum of the older dates
            return max(cutoff_dates)
    
    except Exception:
        pass
    
    return None


class DataManager:
    def __init__(self):
        self.transactions = []  # list of dicts
        self.transaction_hashes = set()  # track fingerprints to detect duplicates
        self.mappings = _load_mappings()
        # Build hashes from existing transactions
        for tx in self.transactions:
            h = self._compute_transaction_hash(tx)
            if h:
                self.transaction_hashes.add(h)

    def _rebuild_hashes(self):
        self.transaction_hashes = set()
        for tx in self.transactions:
            h = self._compute_transaction_hash(tx)
            if h:
                self.transaction_hashes.add(h)

    def _user_data_path(self, user_id):
        project_root = _get_project_root()
        base = os.path.join(project_root, "data", "normalized", "users")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, f"{user_id}.json")

    def _user_uploads_path(self, user_id):
        project_root = _get_project_root()
        base = os.path.join(project_root, "data", "normalized", "usersHistory")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, f"{user_id}_uploads.json")

    def has_user_data(self, user_id):
        path = self._user_data_path(user_id)
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return isinstance(data, list) and len(data) > 0
        except Exception:
            return False

    def load_user_data(self, user_id):
        path = self._user_data_path(user_id)
        # Remove any in-memory transactions for this user before loading
        self.transactions = [t for t in self.transactions if t.get("user_id") != user_id]
        if not os.path.exists(path):
            self._rebuild_hashes()
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
        for tx in data:
            if isinstance(tx, dict) and not tx.get("user_id"):
                tx["user_id"] = user_id
        self.transactions.extend([t for t in data if isinstance(t, dict)])
        self._rebuild_hashes()
        return data

    def save_user_data(self, user_id):
        path = self._user_data_path(user_id)
        data = [t for t in self.transactions if t.get("user_id") == user_id]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        return path

    def get_uploaded_filenames(self, user_id):
        path = self._user_uploads_path(user_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def add_uploaded_filename(self, user_id, filename):
        path = self._user_uploads_path(user_id)
        names = self.get_uploaded_filenames(user_id)
        if filename not in names:
            names.append(filename)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(names, fh, indent=2)
        return names

    def delete_user_data(self, user_id, delete_upload_history=True):
        data_path = self._user_data_path(user_id)
        uploads_path = self._user_uploads_path(user_id)
        if os.path.exists(data_path):
            os.remove(data_path)
        if delete_upload_history and os.path.exists(uploads_path):
            os.remove(uploads_path)
        self.transactions = [t for t in self.transactions if t.get("user_id") != user_id]
        self._rebuild_hashes()

    def add_transactions(self, user_id, txs, duplicate_handling="skip"):
        imported = 0
        skipped = 0
        replaced = 0
        for tx in txs or []:
            if isinstance(tx, dict) and not tx.get("user_id"):
                tx["user_id"] = user_id
            added, rep = self._add_transaction(tx, duplicate_handling=duplicate_handling)
            if added:
                imported += 1
            else:
                skipped += 1
            if rep:
                replaced += 1
        if imported or replaced or skipped:
            self.save_user_data(user_id)
        return {"imported": imported, "skipped": skipped, "replaced": replaced}

    def _compute_transaction_hash(self, tx):
        """Compute a hash from key transaction fields to detect duplicates."""
        import hashlib
        key_fields = (
            str(tx.get("date") or ""),
            str(tx.get("store") or ""),
            str(tx.get("total_price") or ""),
            str(tx.get("item_name") or ""),
        )
        combined = "|".join(key_fields)
        return hashlib.md5(combined.encode()).hexdigest()

    def import_file(self, path, user_id="user", duplicate_handling="skip"):
        """Import file with duplicate handling.
        
        Args:
            path: Path to file
            user_id: User identifier
            duplicate_handling: "skip" (don't import duplicates), "replace" (overwrite existing),
                               or "allow" (import anyway)
        
        Returns:
            Dict with {"imported": count, "skipped": count, "replaced": count}
        """
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        
        # Determine the raw directory and get cutoff date
        raw_dir = os.path.dirname(path)
        cutoff_date = _get_cutoff_date_for_file(path, raw_dir)
        
        _, ext = os.path.splitext(path)
        if ext.lower() in (".csv",):
            return self._import_csv(path, user_id, duplicate_handling, cutoff_date)
        elif ext.lower() in (".json",):
            return self._import_json(path, user_id, duplicate_handling, cutoff_date)
        elif ext.lower() in (".xlsx", ".xls"):
            return self._import_xlsx(path, user_id, duplicate_handling, cutoff_date)
        elif ext.lower() in (".pdf",):
            return self._import_pdf(path, user_id, duplicate_handling, cutoff_date)
        else:
            raise ValueError("Unsupported file type")

    def _add_transaction(self, tx, duplicate_handling="skip"):
        """Add a transaction with duplicate handling.
        
        Returns: (added: bool, replaced: bool)
        """
        h = self._compute_transaction_hash(tx)
        replaced = False
        if h in self.transaction_hashes:
            if duplicate_handling == "skip":
                return False, False
            elif duplicate_handling == "replace":
                # remove old matching transactions
                self.transactions = [t for t in self.transactions if self._compute_transaction_hash(t) != h]
                # we'll add the new one below
                replaced = True

        # Add the new transaction
        self.transactions.append(tx)
        if h:
            self.transaction_hashes.add(h)
        return True, replaced

    def _import_csv(self, path, user_id, duplicate_handling="skip", cutoff_date=None):
        imported = 0
        skipped = 0
        replaced = 0
        source = _infer_source_from_filename(path)
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                # annotate source (first token of filename) so downstream logic can use it
                row["source"] = source
                tx = self._normalize_row(row, user_id)
                
                # Check cutoff date: if specified, only import items on or after the cutoff date
                if cutoff_date and tx.get("date"):
                    if tx.get("date") < cutoff_date:
                        skipped += 1
                        continue
                
                added, rep = self._add_transaction(tx, duplicate_handling=duplicate_handling)
                if added:
                    imported += 1
                else:
                    skipped += 1
                if rep:
                    replaced += 1
        return {"imported": imported, "skipped": skipped, "replaced": replaced}

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

    def _import_json(self, path, user_id, duplicate_handling="skip", cutoff_date=None):
        """Import JSON with some tolerance for common formatting issues (trailing commas, comments)."""
        imported = 0
        skipped = 0
        replaced = 0
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

        source = _infer_source_from_filename(path)
        for row in items:
            # annotate source so normalization can behave differently per source
            if isinstance(row, dict):
                row["source"] = source
            tx = self._normalize_row(row, user_id)
            
            # Check cutoff date: if specified, only import items on or after the cutoff date
            if cutoff_date and tx.get("date"):
                if tx.get("date") < cutoff_date:
                    skipped += 1
                    continue
            
            added, rep = self._add_transaction(tx, duplicate_handling=duplicate_handling)
            if added:
                imported += 1
            else:
                skipped += 1
            if rep:
                replaced += 1
        return {"imported": imported, "skipped": skipped, "replaced": replaced}

    def _import_xlsx(self, path, user_id, duplicate_handling="skip", cutoff_date=None):
        """Import an XLSX where each row is an item. Rows with an isTotalline flag mark receipt totals."""
        # Read the default sheet; if expected Macey columns aren't present, try sheet index 1 (sheet2)
        try:
            df = pd.read_excel(path, engine="openpyxl")
        except (PermissionError, OSError) as e:
            # Permission denied (file locked by Excel/OneDrive). Try copying to a temp file and read again.
            try:
                tmpdir = tempfile.gettempdir()
                tmp_copy = os.path.join(tmpdir, f"copy_{os.path.basename(path)}")
                shutil.copy2(path, tmp_copy)
                df = pd.read_excel(tmp_copy, engine="openpyxl")
            except Exception:
                raise e
        except Exception as e:
            # Any other read error, re-raise
            raise

        # If the sheet doesn't include typical Macey columns, attempt to read sheet2
        if not any(c in df.columns for c in ("UPC", "Description", "Trans", "Amount", "TransPrice")):
            try:
                df = pd.read_excel(path, sheet_name=1, engine="openpyxl")
            except Exception:
                try:
                    # if original read failed due to lock we may need to try the temp copy
                    tmpdir = tempfile.gettempdir()
                    tmp_copy = os.path.join(tmpdir, f"copy_{os.path.basename(path)}")
                    df = pd.read_excel(tmp_copy, sheet_name=1, engine="openpyxl")
                except Exception:
                    pass
        imported = 0
        skipped = 0
        replaced = 0
        for _, row in df.fillna("").iterrows():
            # convert pandas Series to plain dict with string keys
            rowdict = {str(k): (None if pd.isna(v) else v) for k, v in row.items()}
            # annotate source filename first token
            rowdict["source"] = _infer_source_from_filename(path)
            # check for total line markers
            is_total = False
            for key in ("isTotalline", "isTotalLine", "is_total_line", "is_total"):
                if key in rowdict and str(rowdict.get(key)).strip() in ("1", "True", "true", "Y", "y"):
                    is_total = True
                    break
            if is_total:
                # create a receipt-level transaction
                # Normalize date to YYYY-MM-DD only
                raw_date = rowdict.get("date") or rowdict.get("purchase_date")
                norm_date = None
                if raw_date:
                    d_str = str(raw_date).strip()
                    if 'T' in d_str:
                        norm_date = d_str.split('T')[0]
                    elif ' ' in d_str and ':' in d_str:
                        norm_date = d_str.split(' ')[0]
                    else:
                        try:
                            dt = datetime.fromisoformat(d_str)
                            norm_date = dt.date().isoformat()
                        except Exception:
                            match = re.search(r'(\d{4}-\d{2}-\d{2})', d_str)
                            norm_date = match.group(1) if match else d_str
                
                tx = {
                    "transaction_id": f"tx_{len(self.transactions)+1}",
                    "user_id": user_id,
                    "date": norm_date,
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
                
                # Check cutoff date: if specified, only import items on or after the cutoff date
                if cutoff_date and tx.get("date"):
                    if tx.get("date") < cutoff_date:
                        skipped += 1
                        continue
                
                added, rep = self._add_transaction(tx, duplicate_handling=duplicate_handling)
                if added:
                    imported += 1
                else:
                    skipped += 1
                if rep:
                    replaced += 1
            else:
                tx = self._normalize_row(rowdict, user_id)
                
                # Check cutoff date: if specified, only import items on or after the cutoff date
                if cutoff_date and tx.get("date"):
                    if tx.get("date") < cutoff_date:
                        skipped += 1
                        continue
                
                added, rep = self._add_transaction(tx, duplicate_handling=duplicate_handling)
                if added:
                    imported += 1
                else:
                    skipped += 1
                if rep:
                    replaced += 1
        return {"imported": imported, "skipped": skipped, "replaced": replaced}

    def _import_pdf(self, path, user_id, duplicate_handling="skip", cutoff_date=None):
        """Attempt to extract text from a PDF and parse a JSON blob if present."""
        imported = 0
        skipped = 0
        replaced = 0
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
        source = _infer_source_from_filename(path)
        for row in items:
            if isinstance(row, dict):
                row["source"] = source
            tx = self._normalize_row(row, user_id)
            
            # Check cutoff date: if specified, only import items on or after the cutoff date
            if cutoff_date and tx.get("date"):
                if tx.get("date") < cutoff_date:
                    skipped += 1
                    continue
            
            h = self._compute_transaction_hash(tx)
            if h in self.transaction_hashes:
                if duplicate_handling == "skip":
                    skipped += 1
                    continue
                elif duplicate_handling == "replace":
                    self.transactions = [t for t in self.transactions if self._compute_transaction_hash(t) != h]
                    replaced += 1
            self.transactions.append(tx)
            if h:
                self.transaction_hashes.add(h)
            imported += 1
        return {"imported": imported, "skipped": skipped, "replaced": replaced}

    def import_all_from_raw(self, user_id="user", duplicate_handling="skip"):
        """Import all files found in data/raw and return summary dict"""
        project_root = _get_project_root()
        raw_dir = os.path.join(project_root, "data", "raw")
        results = {}
        if not os.path.exists(raw_dir):
            return results
        for fname in os.listdir(raw_dir):
            path = os.path.join(raw_dir, fname)
            if os.path.isfile(path):
                try:
                    res = self.import_file(path, user_id, duplicate_handling=duplicate_handling)
                    results[fname] = res
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
            "source": None,
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

        # Preserve source annotation if present (inferred from filename)
        if "source" in row and row.get("source") not in (None, ""):
            normalized["source"] = row.get("source")

        # (orderno construction moved later, after date parsing and better store-id detection)

        # If this came from Smiths or Maceys, their 'store' field often contains a numeric store id; keep digits only
        if normalized.get("source"):
            src = str(normalized.get("source")).lower()
            if src.startswith("smith") or src.startswith("maceys") or src.startswith("macy"):
                if normalized.get("store") not in (None, ""):
                    s = str(normalized.get("store"))
                    digits = "".join(ch for ch in s if ch.isdigit())
                    if digits:
                        # only replace when digits are present; otherwise keep original
                        normalized["store"] = digits

        # Attempt to parse date - always use YYYY-MM-DD format only, no time
        d = normalized.get("date") or row.get("date") or row.get("purchase_date")
        if d:
            try:
                # Handle various date formats and extract date-only
                d_str = str(d).strip()
                # Remove time portion if present (space followed by time)
                if ' ' in d_str:
                    d_str = d_str.split(' ')[0]
                
                # Now parse the date part
                # Try ISO format first (YYYY-MM-DD)
                if 'T' in d_str:
                    # DateTime with T separator - already handled above
                    normalized["date"] = d_str.split('T')[0]
                elif '-' in d_str and re.match(r'\d{4}-\d{2}-\d{2}', d_str):
                    # ISO format YYYY-MM-DD
                    normalized["date"] = d_str[:10]
                elif '/' in d_str:
                    # Try MM/DD/YYYY or M/D/YYYY format
                    try:
                        dt = datetime.strptime(d_str, "%m/%d/%Y")
                        normalized["date"] = dt.date().isoformat()
                    except ValueError:
                        # Try other slash formats
                        dt = datetime.fromisoformat(d_str)
                        normalized["date"] = dt.date().isoformat()
                else:
                    # Try fromisoformat as fallback
                    dt = datetime.fromisoformat(d_str)
                    normalized["date"] = dt.date().isoformat()
            except Exception:
                # If all else fails, try to extract YYYY-MM-DD pattern
                match = re.search(r'(\d{4}-\d{2}-\d{2})', str(d))
                if match:
                    normalized["date"] = match.group(1)
                else:
                    normalized["date"] = str(d)

        # Determine a canonical numeric store id when possible. Check common fields first,
        # then fall back to digits found in the `store` or `source` fields.
        store_number = None
        for candidate in ("store_number", "storeid", "store_id", "StoreID", "storeNo", "store_no"):
            if candidate in row and row.get(candidate) not in (None, ""):
                store_number = str(row.get(candidate))
                break
        if not store_number and normalized.get("store") not in (None, ""):
            s = str(normalized.get("store"))
            digits = "".join(ch for ch in s if ch.isdigit())
            if digits:
                store_number = digits
        if not store_number and normalized.get("source") not in (None, ""):
            s = str(normalized.get("source"))
            digits = "".join(ch for ch in s if ch.isdigit())
            if digits:
                store_number = digits

        # If there's no explicit orderno, build one using store_number+date when possible,
        # otherwise fall back to date+store_name or date alone.
        if not normalized.get("orderno") and normalized.get("date"):
            date_str = str(normalized.get("date"))
            if store_number:
                normalized["orderno"] = f"{store_number}.{date_str}"
                # ensure the canonical store id is stored in the `store` field
                normalized["store"] = store_number
            else:
                store_str = str(normalized.get("store") or "").strip()
                if store_str:
                    store_safe = re.sub(r"\s+", "_", store_str)
                    normalized["orderno"] = f"{date_str}-{store_safe}"
                else:
                    normalized["orderno"] = date_str

        # Ensure orderno is string and product_upc is number
        if normalized.get("orderno") not in (None, ""):
            normalized["orderno"] = str(normalized.get("orderno"))
        if normalized.get("product_upc") not in (None, ""):
            try:
                # Extract digits and convert to int
                upc_str = str(normalized.get("product_upc"))
                digits = ''.join(ch for ch in upc_str if ch.isdigit())
                normalized["product_upc"] = int(digits) if digits else None
            except (ValueError, TypeError):
                normalized["product_upc"] = None

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

        # Capture UPC/product identifier if present (convert to number)
        if not normalized.get("product_upc"):
            upc_val = None
            if "productupc" in row and row.get("productupc") not in (None, ""):
                upc_val = row.get("productupc")
            elif "UPC" in row and row.get("UPC") not in (None, ""):
                upc_val = row.get("UPC")
            elif "upc" in row and row.get("upc") not in (None, ""):
                upc_val = row.get("upc")
            if upc_val is not None:
                try:
                    digits = ''.join(ch for ch in str(upc_val) if ch.isdigit())
                    normalized["product_upc"] = int(digits) if digits else None
                except (ValueError, TypeError):
                    normalized["product_upc"] = None

        # Prefer retailamt as unit_price (pre-discount) and customerloyamt/TransPrice as total_price (post-discount)
        if normalized.get("unit_price") in (None, ""):
            if "retailamt" in row and row.get("retailamt") not in (None, ""):
                normalized["unit_price"] = row.get("retailamt")
            elif "Price" in row and row.get("Amount") not in (None, ""):
                normalized["unit_price"] = row.get("Amount")

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

        # string type coercion for string fields
        if normalized.get("store") not in (None, ""):
            normalized["store"] = str(normalized.get("store"))
        if normalized.get("item_name") not in (None, ""):
            normalized["item_name"] = str(normalized.get("item_name"))
        if normalized.get("category") not in (None, ""):
            normalized["category"] = str(normalized.get("category"))

        return normalized

    def get_transactions_by_user(self, user_id):
        return [t for t in self.transactions if t.get("user_id") == user_id]
