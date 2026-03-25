"""
Flask Web Application for Spend Analyzer
A simple web interface for managing receipts and getting AI spending insights.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from functools import wraps
import os
import json
import unicodedata
import re
from datetime import datetime
import traceback

# Import existing modules
from spend_analyzer.data_manager import DataManager
from spend_analyzer.llm_client import LLMClient
from spend_analyzer.llm_menu import LLMMenu

# Import database modules
from spend_analyzer.db import Base, get_engine, get_session
from spend_analyzer.models import User, Location, Receipt, LineItem, UserHistory, Recommendation
from spend_analyzer.migrate import migrate_from_json

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


# ====== DATABASE CONFIGURATION ======

# Determine database based on environment
if os.environ.get('FLASK_ENV') == 'production':
    # Use PostgreSQL in production
    DB_URL = os.environ.get('DATABASE_URL')
    if DB_URL and DB_URL.startswith('postgres://'):
        # Fix PostgreSQL URL scheme for SQLAlchemy 1.4+
        DB_URL = DB_URL.replace('postgres://', 'postgresql://', 1)
else:
    # Use SQLite in development
    DB_URL = "sqlite:///spend_data.db"


# === Database Helper Functions ===

def get_user_by_username(username):
    """Get a user by username from database"""
    db_session = get_session(DB_URL)
    try:
        return db_session.query(User).filter_by(username=username).first()
    finally:
        db_session.close()


def get_transactions_from_db(username):
    """
    Get all transactions for a user from database in dict format.
    Returns list of dicts compatible with existing code.
    Excludes soft-deleted receipts and line items.
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return []
        
        transactions = []
        for receipt in user.receipts:
            # Skip soft-deleted receipts
            if not receipt.is_active:
                continue
                
            for item in receipt.line_items:
                # Skip soft-deleted line items
                if not item.is_active:
                    continue
                
                # Skip items with "Unknown" or "Unknown Item" name
                if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                    continue
                
                # Skip items with 0.00 price and 0.00 total
                unit_price = float(item.unit_price or 0)
                total_price = float(item.total_price or 0)
                if unit_price == 0.0 and total_price == 0.0:
                    continue
                    
                tx = {
                    "transaction_id": f"tx_{item.id}",
                    "receipt_id": receipt.id,
                    "line_item_id": item.id,
                    "user_id": username,
                    "date": receipt.date.isoformat() if receipt.date else None,
                    "store": receipt.location.store_number,
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "category": item.category,
                    "orderno": receipt.order_number,
                    "product_upc": item.product_upc,
                    "source": receipt.location.store_name
                }
                transactions.append(tx)
        
        return transactions
    finally:
        db_session.close()


def get_filename_date(filename):
    """
    Extract date from filename in format *_YYYYMMDD.json
    Returns datetime.date object or None if not found
    """
    # Match pattern: _YYYYMMDD. before .json extension
    match = re.search(r'_(\d{8})\.', filename)
    if match:
        try:
            date_str = match.group(1)  # e.g., '20260301'
            return datetime.strptime(date_str, "%Y%m%d").date()
        except:
            pass
    return None


def get_latest_import_date_for_file(username, current_filename):
    """
    Get the latest import date from previously uploaded files with the same base name.
    
    Example: If uploading "Smiths_20260301.json", looks for previously imported
    "Smiths_20250423.json", "Smiths_20250415.json", etc. and returns the latest date.
    
    Args:
        username: User ID
        current_filename: Current file being imported (e.g., "Smiths_20260301.json")
    
    Returns:
        datetime.date object of the latest previous import, or None if no previous imports
    """
    # Extract base name (everything before the date)
    # e.g., "Smiths_20260301.json" -> "Smiths"
    match = re.match(r'^(.+?)_\d{8}\.', current_filename)
    if not match:
        return None
    
    base_name = match.group(1)
    
    # Get all uploaded files for this user
    uploaded_files = get_uploaded_files_from_db(username)
    
    # Find all files with the same base name and extract their dates
    previous_dates = []
    for filename in uploaded_files:
        if filename.startswith(base_name + "_"):
            file_date = get_filename_date(filename)
            if file_date:
                previous_dates.append(file_date)
    
    # Return the latest (max) date, or None if no previous dates
    return max(previous_dates) if previous_dates else None


def filter_transactions_by_date(transactions, cutoff_date):
    """
    Filter transactions to only include those AFTER cutoff_date.
    This prevents duplicates when files contain overlapping data.
    
    Args:
        transactions: List of transaction dicts
        cutoff_date: datetime.date object (from previous file date)
    
    Returns:
        Filtered list of transactions (only those with date > cutoff_date)
    """
    if not cutoff_date:
        return transactions
    
    filtered = []
    for tx in transactions:
        date_str = tx.get("date")
        if not date_str:
            filtered.append(tx)  # Keep items without dates
            continue
        
        try:
            # Try MM/DD/YYYY format first
            tx_date = datetime.strptime(str(date_str)[:10], "%m/%d/%Y").date()
        except:
            try:
                # Try YYYY-MM-DD format
                tx_date = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
            except:
                # If we can't parse it, keep it
                filtered.append(tx)
                continue
        
        # Only include if AFTER (strictly greater than) the cutoff date
        if tx_date > cutoff_date:
            filtered.append(tx)
    
    return filtered


def add_transactions_to_db(username, transactions):
    """
    Add transactions to database for a user.
    Creates Location/Receipt/LineItem records as needed.
    Returns count of imported items.
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return {"imported": 0, "error": "User not found"}
        
        # Group transactions by receipt (orderno or date+store)
        receipt_groups = {}
        
        for tx in transactions:
            # Skip RECEIPT_TOTAL items
            if tx.get("item_name") == "RECEIPT_TOTAL":
                continue
            
            store_number = str(tx.get("store") or "unknown")
            source = tx.get("source") or "Unknown"
            date_str = tx.get("date")
            orderno = tx.get("orderno")
            
            # Create receipt key
            if orderno:
                receipt_key = f"{orderno}"
            else:
                receipt_key = f"{date_str}|{store_number}"
            
            if receipt_key not in receipt_groups:
                receipt_groups[receipt_key] = {
                    "store_number": store_number,
                    "source": source,
                    "date": date_str,
                    "orderno": orderno,
                    "items": []
                }
            
            receipt_groups[receipt_key]["items"].append(tx)
        
        imported = 0
        
        for receipt_key, group in receipt_groups.items():
            # Get or create location
            location = db_session.query(Location).filter_by(
                store_number=group["store_number"],
                store_name=group["source"]
            ).first()
            
            if not location:
                location = Location(
                    store_number=group["store_number"],
                    store_name=group["source"]
                )
                db_session.add(location)
                db_session.flush()
            
            # Parse date
            receipt_date = None
            if group["date"]:
                try:
                    # Try MM/DD/YYYY format first (Smiths, Maceys, etc.)
                    receipt_date = datetime.strptime(str(group["date"])[:10], "%m/%d/%Y").date()
                except:
                    try:
                        # Try YYYY-MM-DD format as fallback
                        receipt_date = datetime.strptime(str(group["date"])[:10], "%Y-%m-%d").date()
                    except:
                        pass
            
            # Check if receipt already exists (by order_number for this user)
            existing_receipt = None
            if group["orderno"]:
                existing_receipt = db_session.query(Receipt).filter_by(
                    user_id=user.id,
                    order_number=group["orderno"]
                ).first()
            
            if existing_receipt:
                receipt = existing_receipt
            else:
                # Calculate total
                total = sum(float(item.get("total_price") or 0) for item in group["items"])
                
                receipt = Receipt(
                    user_id=user.id,
                    location_id=location.id,
                    date=receipt_date,
                    order_number=group["orderno"],
                    total_amount=round(total, 2)
                )
                db_session.add(receipt)
                db_session.flush()
            
            # Add line items
            for item in group["items"]:
                line_item = LineItem(
                    receipt_id=receipt.id,
                    item_name=item.get("item_name") or "Unknown",
                    product_upc=str(item.get("product_upc")) if item.get("product_upc") else None,
                    quantity=float(item.get("quantity") or 1),
                    unit_price=float(item.get("unit_price")) if item.get("unit_price") else None,
                    total_price=float(item.get("total_price") or 0),
                    category=item.get("category")
                )
                db_session.add(line_item)
                imported += 1
        
        db_session.commit()
        return {"imported": imported}
    except Exception as e:
        db_session.rollback()
        return {"imported": 0, "error": str(e)}
    finally:
        db_session.close()


def get_uploaded_files_from_db(username):
    """Get list of uploaded filenames for a user from database"""
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return []
        return [h.filename for h in user.upload_history]
    finally:
        db_session.close()


def add_uploaded_file_to_db(username, filename):
    """Record an uploaded filename for a user in database"""
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False
        
        # Check if already exists
        exists = db_session.query(UserHistory).filter_by(
            user_id=user.id,
            filename=filename
        ).first()
        
        if not exists:
            history = UserHistory(user_id=user.id, filename=filename)
            db_session.add(history)
            db_session.commit()
        
        return True
    except:
        db_session.rollback()
        return False
    finally:
        db_session.close()


def get_recommendations_from_db(username):
    """Get all recommendations for a user from database"""
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return []
        return [rec.to_dict() for rec in user.recommendations]
    finally:
        db_session.close()


def save_recommendation_to_db(username, question, response, category="Other"):
    """Save a recommendation to database"""
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False
        
        rec = Recommendation(
            user_id=user.id,
            category=category,
            question=question,
            response=response
        )
        db_session.add(rec)
        db_session.commit()
        return True
    except:
        db_session.rollback()
        return False
    finally:
        db_session.close()


def delete_recommendation_from_db(username, rec_index):
    """Delete a recommendation by index for a user"""
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False
        
        recs = list(user.recommendations)
        if 0 <= rec_index < len(recs):
            db_session.delete(recs[rec_index])
            db_session.commit()
            return True
        return False
    except:
        db_session.rollback()
        return False
    finally:
        db_session.close()


def delete_user_data_from_db(username, delete_upload_history=True):
    """Delete all data for a user from database"""
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False
        
        # Delete all receipts (cascade deletes line items)
        for receipt in user.receipts:
            db_session.delete(receipt)
        
        # Delete upload history if requested
        if delete_upload_history:
            for history in user.upload_history:
                db_session.delete(history)
        
        # Delete recommendations
        for rec in user.recommendations:
            db_session.delete(rec)
        
        db_session.commit()
        return True
    except:
        db_session.rollback()
        return False
    finally:
        db_session.close()


# === Soft Delete and Hard Delete Functions ===

def soft_delete_receipt(username, receipt_id):
    """
    Soft delete a receipt - sets is_active to False
    Also soft deletes all associated line items
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False, "User not found"
        
        receipt = db_session.query(Receipt).filter_by(id=receipt_id, user_id=user.id).first()
        if not receipt:
            return False, "Receipt not found"
        
        # Soft delete the receipt
        receipt.is_active = False
        receipt.updated_at = datetime.utcnow()
        
        # Soft delete all line items
        for item in receipt.line_items:
            item.is_active = False
            item.updated_at = datetime.utcnow()
        
        db_session.commit()
        return True, "Receipt deleted successfully"
    except Exception as e:
        db_session.rollback()
        return False, str(e)
    finally:
        db_session.close()


def hard_delete_receipt(username, receipt_id):
    """
    Hard delete a receipt - completely removes it and all associated line items
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False, "User not found"
        
        receipt = db_session.query(Receipt).filter_by(id=receipt_id, user_id=user.id).first()
        if not receipt:
            return False, "Receipt not found"
        
        # Delete the receipt (cascade will delete line items)
        db_session.delete(receipt)
        db_session.commit()
        return True, "Receipt permanently deleted"
    except Exception as e:
        db_session.rollback()
        return False, str(e)
    finally:
        db_session.close()


def soft_delete_line_item(username, line_item_id):
    """
    Soft delete a line item - sets is_active to False
    """
    db_session = get_session(DB_URL)
    try:
        # Verify user owns this line item
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False, "User not found"
        
        # Query line item through receipt to verify ownership
        line_item = db_session.query(LineItem).join(Receipt).filter(
            LineItem.id == line_item_id,
            Receipt.user_id == user.id
        ).first()
        
        if not line_item:
            return False, "Line item not found"
        
        # Soft delete the line item
        line_item.is_active = False
        line_item.updated_at = datetime.utcnow()
        
        db_session.commit()
        return True, "Item deleted successfully"
    except Exception as e:
        db_session.rollback()
        return False, str(e)
    finally:
        db_session.close()


def hard_delete_line_item(username, line_item_id):
    """
    Hard delete a line item - completely removes it
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False, "User not found"
        
        # Query line item through receipt to verify ownership
        line_item = db_session.query(LineItem).join(Receipt).filter(
            LineItem.id == line_item_id,
            Receipt.user_id == user.id
        ).first()
        
        if not line_item:
            return False, "Line item not found"
        
        # Delete the line item
        db_session.delete(line_item)
        db_session.commit()
        return True, "Item permanently deleted"
    except Exception as e:
        db_session.rollback()
        return False, str(e)
    finally:
        db_session.close()


def get_receipt_for_editing(username, receipt_id):
    """
    Get receipt data for editing, including all line items with discount info
    Returns tuple: (receipt_dict, line_items_list)
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return None, []
        
        receipt = db_session.query(Receipt).filter_by(id=receipt_id, user_id=user.id).first()
        if not receipt:
            return None, []
        
        receipt_dict = {
            "id": receipt.id,
            "date": receipt.date.isoformat() if receipt.date else "",
            "store_number": receipt.location.store_number,
            "store_name": receipt.location.store_name,
            "order_number": receipt.order_number,
            "total_amount": receipt.total_amount,
            "location_id": receipt.location_id
        }
        
        line_items = []
        for item in receipt.line_items:
            # Skip RECEIPT_TOTAL and DISCOUNT items (legacy support)
            if item.item_name == "RECEIPT_TOTAL" or (item.item_name and item.item_name.startswith("DISCOUNT (")):
                continue
            
            # Skip items with "Unknown" or "Unknown Item" name
            if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                continue
            
            # Skip items with 0.00 price and 0.00 total
            unit_price = float(item.unit_price or 0)
            total_price = float(item.total_price or 0)
            if unit_price == 0.0 and total_price == 0.0:
                continue
            
            # Calculate discount from the item data: (unit_price * quantity) - total_price
            if item.unit_price and item.quantity:
                discount = (item.unit_price * item.quantity) - item.total_price
            else:
                discount = 0
            
            line_items.append({
                "id": item.id,
                "item_name": item.item_name,
                "product_upc": item.product_upc,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "discount": discount
            })
        
        return receipt_dict, line_items
    finally:
        db_session.close()


def update_receipt_in_db(username, receipt_id, receipt_data, line_items_data):
    """
    Update a receipt and its line items (discount stored as price difference, no separate DISCOUNT rows)
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return False, "User not found"
        
        receipt = db_session.query(Receipt).filter_by(id=receipt_id, user_id=user.id).first()
        if not receipt:
            return False, "Receipt not found"
        
        # Update receipt
        from datetime import datetime as dt
        receipt.date = dt.strptime(receipt_data['date'], '%Y-%m-%d').date()
        receipt.order_number = receipt_data.get('order_number')
        receipt.total_amount = float(receipt_data.get('total_amount', 0))
        receipt.updated_at = datetime.utcnow()
        
        # Update or create line items
        existing_ids = set()
        
        for item_data in line_items_data:
            item_id = item_data.get('id')
            discount = float(item_data.get('discount', 0))
            quantity = float(item_data.get('quantity', 1))
            unit_price = float(item_data.get('unit_price', 0)) if item_data.get('unit_price') else None
            
            # Calculate total_price: (unit_price * quantity) - discount
            subtotal = unit_price * quantity if unit_price else 0
            total_price = subtotal - discount
            
            if item_id:
                # Update existing line item
                line_item = db_session.query(LineItem).filter_by(id=item_id, receipt_id=receipt.id).first()
                if line_item:
                    line_item.item_name = item_data.get('item_name', '')
                    line_item.product_upc = item_data.get('product_upc')
                    line_item.quantity = quantity
                    line_item.unit_price = unit_price
                    line_item.total_price = total_price
                    line_item.updated_at = datetime.utcnow()
                    existing_ids.add(item_id)
            else:
                # Create new line item
                new_item = LineItem(
                    receipt_id=receipt.id,
                    item_name=item_data.get('item_name', ''),
                    product_upc=item_data.get('product_upc'),
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                db_session.add(new_item)
                db_session.flush()
                existing_ids.add(new_item.id)
        
        # Delete line items that were not provided
        for item in receipt.line_items:
            if item.id not in existing_ids:
                db_session.delete(item)
        
        db_session.commit()
        return True, "Receipt updated successfully"
    except Exception as e:
        db_session.rollback()
        return False, str(e)
    finally:
        db_session.close()


def filter_context_by_question(transactions, question):
    """
    Intelligently filter transactions based on the user's question.
    Extracts years, date ranges, store names, and item keywords.
    Returns filtered transactions and a summary of what was filtered.
    """
    question_lower = question.lower()
    filtered = transactions
    filters_applied = []
    
    # Extract years mentioned (e.g., "2024", "2025")
    years = re.findall(r'\b(20\d{2})\b', question)
    
    # Extract month-year patterns (e.g., "November 2025", "Nov 2025")
    month_patterns = re.findall(r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*(\d{4})', question_lower)
    
    # Extract specific date patterns (e.g., "2025-11-22")
    specific_dates = re.findall(r'\b(\d{4}-\d{2}-\d{2})\b', question)
    
    # Map month names to numbers
    month_map = {
        'january': '01', 'jan': '01', 'february': '02', 'feb': '02',
        'march': '03', 'mar': '03', 'april': '04', 'apr': '04',
        'may': '05', 'june': '06', 'jun': '06', 'july': '07', 'jul': '07',
        'august': '08', 'aug': '08', 'september': '09', 'sep': '09',
        'october': '10', 'oct': '10', 'november': '11', 'nov': '11',
        'december': '12', 'dec': '12'
    }
    
    # Filter by specific dates first
    if specific_dates:
        filtered = [t for t in filtered if any(d in t.get('date', '') for d in specific_dates)]
        filters_applied.append(f"dates: {', '.join(specific_dates)}")
    
    # Filter by month-year if mentioned
    elif month_patterns:
        month_filters = []
        for month_name, year in month_patterns:
            month_num = month_map.get(month_name.lower())
            if month_num:
                prefix = f"{year}-{month_num}"
                month_filters.append(prefix)
        if month_filters:
            filtered = [t for t in filtered if any(t.get('date', '').startswith(p) for p in month_filters)]
            filters_applied.append(f"months: {', '.join(month_filters)}")
    
    # Filter by years if mentioned
    elif years:
        filtered = [t for t in filtered if any(t.get('date', '').startswith(y) for y in years)]
        filters_applied.append(f"years: {', '.join(years)}")
    
    # Extract store names - check common stores mentioned in question
    store_keywords = ['costco', 'walmart', 'target', 'smiths', 'maceys', 'kroger', 'safeway', 
                      'whole foods', 'trader joe', 'aldi', 'winco', 'amazon', 'sams club']
    mentioned_stores = [s for s in store_keywords if s in question_lower]
    
    if mentioned_stores:
        store_filtered = [t for t in filtered 
                         if any(s in t.get('source', '').lower() or s in t.get('store', '').lower() 
                                for s in mentioned_stores)]
        if store_filtered:
            filtered = store_filtered
            filters_applied.append(f"stores: {', '.join(mentioned_stores)}")
    
    # If filter resulted in 0 transactions, fall back to all data
    if not filtered and transactions:
        filtered = transactions
        filters_applied = ["no matches found, returning all transactions"]
    
    return filtered, filters_applied


def slim_context(transactions):
    """
    Consolidate transactions by date+store to reduce payload size.
    Uses short field names: d=date, s=store, i=items, n=name, q=qty, p=price, u=unit
    """
    from collections import defaultdict
    
    # Group by date and store
    grouped = defaultdict(list)
    for t in transactions:
        store = t.get('source') or t.get('store') or 'unknown'
        date = t.get('date') or 'unknown'
        key = (date, store)
        
        # Truncate item name to 25 chars
        item_name = (t.get('item_name') or '')[:25]
        
        item_data = {
            'n': item_name,
            'p': t.get('total_price'),
        }
        
        # Only include qty if not 1
        qty = t.get('quantity')
        if qty is not None and qty != 1 and qty != 1.0:
            item_data['q'] = qty
        
        # Include unit_price only if different from total
        unit_price = t.get('unit_price')
        total_price = t.get('total_price')
        if unit_price is not None and total_price is not None and unit_price != total_price:
            item_data['u'] = unit_price
        
        grouped[key].append(item_data)
    
    # Convert to list format with short keys
    result = []
    for (date, store), items in sorted(grouped.items(), reverse=True):
        result.append({
            'd': date,
            's': store,
            'i': items
        })
    
    return result


def context_to_table(transactions):
    """
    Convert transactions to a compact pipe-delimited table format for LLM.
    This is much more token-efficient than JSON.
    Returns: String with header row and data rows
    """
    from jinja2 import Template
    
    # Jinja template for compact table format
    table_template = Template("""Date|Store|Item|Qty|Price
{% for t in transactions -%}
{{ t.date or 'unknown' }}|{{ (t.source or t.store or 'unknown')[:12] }}|{{ (t.item_name or '')[:20] }}|{{ t.quantity or 1 }}|{{ "%.2f"|format(t.total_price or 0) }}
{% endfor %}""")
    
    # Filter out RECEIPT_TOTAL entries for cleaner context
    filtered = [t for t in transactions if t.get('item_name') != 'RECEIPT_TOTAL']
    
    return table_template.render(transactions=filtered)


def context_to_summary(transactions):
    """
    Create a brief summary of transaction data for LLM context.
    Even more compact than table format.
    """
    from collections import defaultdict
    from jinja2 import Template
    
    # Group by store
    store_totals = defaultdict(lambda: {'items': 0, 'total': 0.0})
    date_range = {'min': None, 'max': None}
    
    for t in transactions:
        if t.get('item_name') == 'RECEIPT_TOTAL':
            continue
        store = t.get('source') or t.get('store') or 'unknown'
        store_totals[store]['items'] += 1
        store_totals[store]['total'] += float(t.get('total_price') or 0)
        
        date = t.get('date')
        if date:
            if not date_range['min'] or date < date_range['min']:
                date_range['min'] = date
            if not date_range['max'] or date > date_range['max']:
                date_range['max'] = date
    
    summary_template = Template("""Period: {{ date_min }} to {{ date_max }}
Stores: {% for store, data in stores.items() %}{{ store }}(${{ "%.2f"|format(data.total) }}/{{ data.items }}items){% if not loop.last %}, {% endif %}{% endfor %}
Total: ${{ "%.2f"|format(grand_total) }} across {{ item_count }} items""")
    
    grand_total = sum(d['total'] for d in store_totals.values())
    item_count = sum(d['items'] for d in store_totals.values())
    
    return summary_template.render(
        date_min=date_range['min'] or 'unknown',
        date_max=date_range['max'] or 'unknown',
        stores=dict(store_totals),
        grand_total=grand_total,
        item_count=item_count
    )


app = Flask(__name__)

# Load configuration
config_name = os.environ.get('FLASK_ENV', 'development')
if config_name == 'production':
    from config import ProductionConfig
    app.config.from_object(ProductionConfig)
else:
    from config import DevelopmentConfig
    app.config.from_object(DevelopmentConfig)

# Override secret key from environment if set
if os.environ.get('SECRET_KEY'):
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
else:
    # Generate a random secret key for development
    app.secret_key = os.urandom(24)

# Initialize shared instances
dm = DataManager()
llm = LLMClient()
llm_menu = LLMMenu(llm, dm)

# Initialize database
engine = get_engine(DB_URL)
Base.metadata.create_all(engine)


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """Get the current logged-in user from database"""
    if 'user_id' not in session:
        return None
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(id=session['user_id']).first()
        return user
    finally:
        db_session.close()


def normalize_filename(s):
    """Normalize unicode and replace common apostrophe variants for filename comparison."""
    s = unicodedata.normalize('NFC', s)
    return s.replace(''', "'").replace(''', "'").replace('`', "'")


# === Authentication Routes ===

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login and signup page"""
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    error = None
    success = None
    
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        db_session = get_session(DB_URL)
        try:
            if action == 'signup':
                # Create new account
                confirm_password = request.form.get('confirm_password', '')
                
                if not username or not password:
                    error = 'Username and password are required'
                elif password != confirm_password:
                    error = 'Passwords do not match'
                elif db_session.query(User).filter_by(username=username).first():
                    error = 'Username already exists'
                else:
                    new_user = User(username=username)
                    new_user.set_password(password)  # Hash the password
                    db_session.add(new_user)
                    db_session.commit()
                    success = 'Account created! You can now sign in.'
            
            elif action == 'login':
                # Login existing user
                user = db_session.query(User).filter_by(username=username).first()
                if user and user.check_password(password):  # Verify hashed password
                    session['user_id'] = user.id
                    session['username'] = user.username
                    session['theme'] = user.theme or 'default'
                    user.last_login = datetime.utcnow()
                    db_session.commit()
                    return redirect(url_for('index'))
                else:
                    error = 'Invalid username or password'
        finally:
            db_session.close()
    
    return render_template('login.html', error=error, success=success)


@app.route('/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    return redirect(url_for('login'))


# === Main Routes ===

@app.route('/')
@login_required
def index():
    """Main route - redirect to analytics dashboard"""
    return redirect(url_for('analytics_page'))


@app.route('/analytics')
@login_required
def analytics_page():
    """Analytics dashboard with comprehensive spending reports"""
    user_id = session.get('username', '')
    
    transactions = []
    if user_id:
        transactions = get_transactions_from_db(user_id)
    
    return render_template(
        'analytics.html',
        user_id=user_id,
        transactions=transactions,
        transaction_count=len(transactions)
    )


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_receipt_page():
    """Route for the add receipt page - displays form and handles submission"""
    user_id = session.get('username', '')
    
    if request.method == 'GET':
        # Display the add receipt form
        transactions = []
        if user_id:
            transactions = get_transactions_from_db(user_id)
        
        return render_template(
            'add_receipt.html',
            user_id=user_id,
            transactions=transactions,
            transaction_count=len(transactions)
        )
    
    # POST - Handle form submission
    try:
        store_number = request.form.get('store_number', '').strip()
        store_name = request.form.get('store_name', '').strip() or 'unknown'
        date_str = request.form.get('date', '').strip()
        
        # Validate required fields
        if not user_id:
            return redirect(url_for('add_receipt_page', message='Please load a user first', type='error'))
        
        if not store_number:
            return redirect(url_for('add_receipt_page', message='Store number is required', type='error'))
        
        if not date_str:
            return redirect(url_for('add_receipt_page', message='Date is required', type='error'))
        
        # Parse items from form data
        items = []
        i = 0
        while True:
            item_name = request.form.get(f'items[{i}][name]')
            if item_name is None:
                break
            
            item_price = request.form.get(f'items[{i}][price]', '0')
            item_qty = request.form.get(f'items[{i}][qty]', '1')
            item_discount = request.form.get(f'items[{i}][discount]', '0')
            
            if item_name.strip():  # Only add non-empty items
                items.append({
                    'name': item_name.strip(),
                    'price': float(item_price) if item_price else 0,
                    'qty': int(item_qty) if item_qty else 1,
                    'discount': float(item_discount) if item_discount else 0
                })
            i += 1
        
        if not items:
            return redirect(url_for('add_receipt_page', message='At least one item is required', type='error'))
        
        # Create transactions list
        orderno = f"{store_number}.{date_str}"
        
        transactions = []
        final_total = 0
        
        for item in items:
            item_subtotal = item['price'] * item['qty']
            item_discount = item['discount']
            item_total = item_subtotal - item_discount
            final_total += item_total
            
            tx = {
                'user_id': user_id,
                'item_name': item['name'],
                'unit_price': item['price'],
                'quantity': item['qty'],
                'total_price': item_total,
                'store': store_number,
                'source': store_name,
                'date': date_str,
                'orderno': orderno
            }
            transactions.append(tx)
            
            # Add discount line item if there's a discount
            if item_discount > 0:
                transactions.append({
                    'user_id': user_id,
                    'item_name': f"DISCOUNT ({item['name']})",
                    'unit_price': -item_discount,
                    'quantity': 1,
                    'total_price': -item_discount,
                    'store': store_number,
                    'source': store_name,
                    'date': date_str,
                    'orderno': orderno
                })
        
        # Add receipt total (for reference, not counted in stats)
        transactions.append({
            'user_id': user_id,
            'item_name': 'RECEIPT_TOTAL',
            'unit_price': 0,
            'quantity': 1,
            'total_price': final_total,
            'store': store_number,
            'source': store_name,
            'date': date_str,
            'orderno': orderno
        })
        
        # Save to database
        result = add_transactions_to_db(user_id, transactions)
        
        # Redirect to data view (receipts list) with success message
        return redirect(url_for('data_page', message='Receipt saved successfully!', type='success'))
        
    except Exception as e:
        return redirect(url_for('add_receipt_page', message=f'Error: {str(e)}', type='error'))


@app.route('/import')
@login_required
def import_page():
    """Route for the import files page"""
    user_id = session.get('username', '')
    
    transactions = []
    if user_id:
        transactions = get_transactions_from_db(user_id)
    
    return render_template(
        'import.html',
        user_id=user_id,
        transactions=transactions,
        transaction_count=len(transactions)
    )


@app.route('/chat')
@login_required
def chat_page():
    """Route for the AI insights/chat page"""
    user_id = session.get('username', '')
    
    transactions = []
    if user_id:
        transactions = get_transactions_from_db(user_id)
    
    return render_template(
        'chat.html',
        user_id=user_id,
        transactions=transactions,
        transaction_count=len(transactions)
    )


@app.route('/saved')
@login_required
def saved_page():
    """Route for the saved insights page"""
    user_id = session.get('username', '')
    
    transactions = []
    recommendations = []
    if user_id:
        transactions = get_transactions_from_db(user_id)
        recommendations = get_recommendations_from_db(user_id)
    
    return render_template(
        'saved.html',
        user_id=user_id,
        transactions=transactions,
        transaction_count=len(transactions),
        recommendations=recommendations
    )


@app.route('/data')
@login_required
def data_page():
    """Route for the view data page"""
    user_id = session.get('username', '')
    
    transactions = []
    if user_id:
        transactions = get_transactions_from_db(user_id)
    
    return render_template(
        'data.html',
        user_id=user_id,
        transactions=transactions,
        transaction_count=len(transactions)
    )


# === Edit and Delete Routes ===

@app.route('/receipt/<int:receipt_id>/edit', methods=['GET'])
@login_required
def edit_receipt_page(receipt_id):
    """Route to display edit receipt form with pre-filled data"""
    user_id = session.get('username', '')
    
    receipt_data, line_items = get_receipt_for_editing(user_id, receipt_id)
    if not receipt_data:
        return redirect(url_for('data_page', message='Receipt not found', type='error'))
    
    transactions = []
    if user_id:
        transactions = get_transactions_from_db(user_id)
    
    return render_template(
        'edit_receipt.html',
        user_id=user_id,
        receipt=receipt_data,
        line_items=line_items,
        transactions=transactions,
        transaction_count=len(transactions)
    )


@app.route('/receipt/<int:receipt_id>/delete', methods=['GET'])
@login_required
def delete_receipt_page(receipt_id):
    """Route to display delete confirmation page"""
    user_id = session.get('username', '')
    
    receipt_data, line_items = get_receipt_for_editing(user_id, receipt_id)
    if not receipt_data:
        return redirect(url_for('data_page', message='Receipt not found', type='error'))
    
    return render_template(
        'delete_receipt.html',
        user_id=user_id,
        receipt=receipt_data,
        line_items=line_items
    )


@app.route('/receipt/<int:receipt_id>/update', methods=['POST'])
@login_required
def update_receipt(receipt_id):
    """Route to update an existing receipt"""
    user_id = session.get('username', '')
    
    try:
        # Parse receipt data
        receipt_data = {
            'date': request.form.get('date', '').strip(),
            'store_number': request.form.get('store_number', '').strip(),
            'store_name': request.form.get('store_name', '').strip() or 'unknown',
            'order_number': request.form.get('order_number', '').strip(),
            'total_amount': request.form.get('total_amount', '0')
        }
        
        # Validate required fields
        if not receipt_data['date']:
            return redirect(url_for('edit_receipt_page', receipt_id=receipt_id, 
                                   message='Date is required', type='error'))
        
        if not receipt_data['store_number']:
            return redirect(url_for('edit_receipt_page', receipt_id=receipt_id,
                                   message='Store number is required', type='error'))
        
        # Parse line items from form data
        line_items = []
        i = 0
        total = 0
        while True:
            item_name = request.form.get(f'items[{i}][name]')
            if item_name is None:
                break
            
            if item_name.strip():
                item_id = request.form.get(f'items[{i}][id]')
                item_price = float(request.form.get(f'items[{i}][price]', '0') or '0')
                item_qty = float(request.form.get(f'items[{i}][qty]', '1') or '1')
                item_discount = float(request.form.get(f'items[{i}][discount]', '0') or '0')
                item_subtotal = item_price * item_qty
                item_total = item_subtotal - item_discount
                total += item_total
                
                line_items.append({
                    'id': int(item_id) if item_id else None,
                    'item_name': item_name.strip(),
                    'quantity': item_qty,
                    'unit_price': item_price,
                    'total_price': item_total,
                    'product_upc': request.form.get(f'items[{i}][upc]'),
                    'discount': item_discount
                })
            i += 1
        
        if not line_items:
            return redirect(url_for('edit_receipt_page', receipt_id=receipt_id,
                                   message='At least one item is required', type='error'))
        
        receipt_data['total_amount'] = total
        
        # Update in database
        success, message = update_receipt_in_db(user_id, receipt_id, receipt_data, line_items)
        
        if success:
            return redirect(url_for('data_page', message='Receipt updated successfully!', type='success'))
        else:
            return redirect(url_for('edit_receipt_page', receipt_id=receipt_id,
                                   message=f'Error: {message}', type='error'))
    
    except Exception as e:
        return redirect(url_for('edit_receipt_page', receipt_id=receipt_id,
                               message=f'Error: {str(e)}', type='error'))


@app.route('/api/receipt/<int:receipt_id>/delete', methods=['POST'])
@login_required
def delete_receipt(receipt_id):
    """Route to delete a receipt (soft or hard delete via API)"""
    user_id = session.get('username', '')
    delete_type = request.json.get('delete_type', 'soft')  # 'soft' or 'hard'
    
    try:
        if delete_type == 'hard':
            success, message = hard_delete_receipt(user_id, receipt_id)
        else:
            success, message = soft_delete_receipt(user_id, receipt_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/lineitem/<int:line_item_id>/delete', methods=['POST'])
@login_required
def delete_line_item(line_item_id):
    """Route to delete a line item (soft or hard delete via API)"""
    user_id = session.get('username', '')
    delete_type = request.json.get('delete_type', 'soft')  # 'soft' or 'hard'
    
    try:
        if delete_type == 'hard':
            success, message = hard_delete_line_item(user_id, line_item_id)
        else:
            success, message = soft_delete_line_item(user_id, line_item_id)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/settings')
@login_required
def settings_page():
    """Route for the settings page"""
    user_id = session.get('username', '')
    user = get_current_user()
    theme = user.theme if user else 'default'
    
    transactions = []
    if user_id:
        transactions = get_transactions_from_db(user_id)
    
    return render_template(
        'settings.html',
        user_id=user_id,
        transactions=transactions,
        transaction_count=len(transactions),
        theme=theme
    )


@app.route('/api/update_theme', methods=['POST'])
@login_required
def update_theme():
    """API endpoint to update user's theme preference"""
    try:
        data = request.json
        theme = data.get('theme', 'default')
        
        db_session = get_session(DB_URL)
        try:
            user = db_session.query(User).filter_by(id=session.get('user_id')).first()
            if user:
                user.theme = theme
                db_session.commit()
                session['theme'] = theme
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'User not found'})
        finally:
            db_session.close()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/add_receipt', methods=['POST'])
@login_required
def add_receipt():
    """API endpoint to add a new receipt"""
    try:
        data = request.json
        user_id = session.get('username')
        store_number = data.get('store_number')
        store_name = data.get('store_name', 'unknown')
        date_str = data.get('date')
        items = data.get('items', [])
        
        if not items:
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        orderno = f"{store_number}.{date_str}"
        
        transactions = []
        final_total = 0
        for item in items:
            item_subtotal = float(item.get('price', 0)) * int(item.get('qty', 1))
            item_discount = float(item.get('discount', 0) or 0)
            item_total = item_subtotal - item_discount
            final_total += item_total
            
            tx = {
                'user_id': user_id,
                'item_name': item.get('name'),
                'unit_price': float(item.get('price', 0)),
                'quantity': int(item.get('qty', 1)),
                'total_price': item_total,
                'store': store_number,
                'source': store_name,
                'date': date_str,
                'orderno': orderno
            }
            transactions.append(tx)
        
        # Add receipt total (for reference, not counted in stats)
        transactions.append({
            'user_id': user_id,
            'item_name': 'RECEIPT_TOTAL',
            'unit_price': 0,
            'quantity': 1,
            'total_price': final_total,
            'store': store_number,
            'source': store_name,
            'date': date_str,
            'orderno': orderno
        })
        
        result = add_transactions_to_db(user_id, transactions)
        return jsonify({'success': True, 'imported': result.get('imported', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# === API v1 Routes (Versioned API) ===
# These endpoints follow REST conventions with /api/v1/ prefix

@app.route('/api/v1/items', methods=['GET'])
@login_required
def api_v1_get_all_items():
    """
    Get all line items for the authenticated user.
    
    Returns:
        JSON array of all line items with their details.
        HTTP 200: Success
        HTTP 401: Unauthorized (not logged in)
    
    Example response:
        [
            {
                "id": 1,
                "line_item_id": 1,
                "item_name": "Milk",
                "quantity": 1,
                "unit_price": 3.99,
                "total_price": 3.99,
                "receipt_id": 1,
                "date": "2026-03-25",
                "store": "Smiths",
                "category": "Dairy"
            },
            ...
        ]
    """
    user_id = session.get('username', '')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        transactions = get_transactions_from_db(user_id)
        # Filter out RECEIPT_TOTAL items
        items = [t for t in transactions if t.get('item_name') != 'RECEIPT_TOTAL']
        return jsonify(items), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/items/<int:item_id>', methods=['GET'])
@login_required
def api_v1_get_item(item_id):
    """
    Get a single line item by ID for the authenticated user.
    
    Args:
        item_id: The line_item_id to retrieve
    
    Returns:
        JSON object of the line item.
        HTTP 200: Success
        HTTP 404: Item not found
        HTTP 401: Unauthorized (not logged in)
    
    Example response:
        {
            "id": 1,
            "line_item_id": 1,
            "item_name": "Milk",
            "quantity": 1,
            "unit_price": 3.99,
            "total_price": 3.99,
            "receipt_id": 1,
            "date": "2026-03-25",
            "store": "Smiths",
            "category": "Dairy"
        }
    """
    user_id = session.get('username', '')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        transactions = get_transactions_from_db(user_id)
        
        # Find the item by line_item_id
        item = None
        for t in transactions:
            if t.get('line_item_id') == item_id and t.get('item_name') != 'RECEIPT_TOTAL':
                item = t
                break
        
        if item is None:
            return jsonify({
                'error': 'Item not found',
                'item_id': item_id
            }), 404
        
        return jsonify(item), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics', methods=['GET'])
@login_required
def get_analytics():
    """
    Comprehensive analytics endpoint with detailed breakdown of:
    - Summary statistics
    - Monthly and weekly trends
    - Store breakdown with percentages
    - Category breakdown
    - Top items and stores
    - Daily spending patterns
    - Recent activity
    """
    try:
        user_id = session.get('username')
        db_session = get_session(DB_URL)
        
        try:
            user = db_session.query(User).filter_by(username=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            from collections import defaultdict
            from datetime import datetime, timedelta
            from decimal import Decimal
            
            # Fetch all active receipts and line items
            receipts = [r for r in user.receipts if r.is_active]
            
            if not receipts:
                return jsonify({
                    'summary': {
                        'totalSpent': 0,
                        'itemCount': 0,
                        'transactionCount': 0,
                        'storeCount': 0,
                        'averageTransaction': 0,
                        'dateRange': {'start': None, 'end': None}
                    },
                    'byMonth': [],
                    'byStore': [],
                    'byCategory': [],
                    'topItems': [],
                    'topStores': [],
                    'weeklyPattern': {},
                    'recent': [],
                    'insights': []
                })
            
            # ====== SUMMARY STATISTICS ======
            total_spent = 0
            item_count = 0
            store_names = set()
            all_dates = []
            transaction_dates = defaultdict(float)
            
            for receipt in receipts:
                if receipt.date:
                    all_dates.append(receipt.date)
                    transaction_dates[receipt.date] += receipt.total_amount
                
                store_names.add(receipt.location.store_name)
                
                for item in receipt.line_items:
                    if item.is_active:
                        # Skip items with "Unknown" or "Unknown Item" name
                        if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                            continue
                        
                        # Skip items with 0.00 price and 0.00 total
                        unit_price = float(item.unit_price or 0)
                        total_price = float(item.total_price or 0)
                        if unit_price == 0.0 and total_price == 0.0:
                            continue
                        
                        item_count += 1
                        total_spent += item.total_price
            
            summary = {
                'totalSpent': round(float(total_spent), 2),
                'itemCount': item_count,
                'transactionCount': len(receipts),
                'storeCount': len(store_names),
                'averageTransaction': round(float(total_spent / len(receipts)), 2) if receipts else 0,
                'dateRange': {
                    'start': min(all_dates).isoformat() if all_dates else None,
                    'end': max(all_dates).isoformat() if all_dates else None
                }
            }
            
            # ====== MONTHLY BREAKDOWN ======
            monthly_data = defaultdict(lambda: {'spent': 0, 'count': 0, 'receipts': 0})
            
            for receipt in receipts:
                if receipt.date:
                    month_key = receipt.date.strftime('%Y-%m')
                    monthly_data[month_key]['receipts'] += 1
                    monthly_data[month_key]['spent'] += receipt.total_amount
                    
                    for item in receipt.line_items:
                        if item.is_active:
                            # Skip items with "Unknown" or "Unknown Item" name
                            if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                                continue
                            
                            # Skip items with 0.00 price and 0.00 total
                            unit_price = float(item.unit_price or 0)
                            total_price = float(item.total_price or 0)
                            if unit_price == 0.0 and total_price == 0.0:
                                continue
                            
                            monthly_data[month_key]['count'] += 1
            
            by_month = []
            for month in sorted(monthly_data.keys(), reverse=True):
                data = monthly_data[month]
                by_month.append({
                    'month': month,
                    'spent': round(float(data['spent']), 2),
                    'itemCount': data['count'],
                    'receiptCount': data['receipts'],
                    'averageReceipt': round(float(data['spent'] / data['receipts']), 2) if data['receipts'] else 0
                })
            
            # ====== STORE BREAKDOWN ======
            store_data = defaultdict(lambda: {'spent': 0, 'count': 0, 'receipts': 0, 'dates': []})
            
            for receipt in receipts:
                store_name = receipt.location.store_name
                store_data[store_name]['receipts'] += 1
                store_data[store_name]['spent'] += receipt.total_amount
                if receipt.date:
                    store_data[store_name]['dates'].append(receipt.date)
                
                for item in receipt.line_items:
                    if item.is_active:
                        # Skip items with "Unknown" or "Unknown Item" name
                        if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                            continue
                        
                        # Skip items with 0.00 price and 0.00 total
                        unit_price = float(item.unit_price or 0)
                        total_price = float(item.total_price or 0)
                        if unit_price == 0.0 and total_price == 0.0:
                            continue
                        
                        store_data[store_name]['count'] += 1
            
            by_store = []
            for store_name in sorted(store_data.keys()):
                data = store_data[store_name]
                pct = (data['spent'] / total_spent * 100) if total_spent > 0 else 0
                
                # Calculate frequency (visits per month)
                if data['dates']:
                    date_range = (max(data['dates']) - min(data['dates'])).days
                    months_range = max(date_range / 30, 1)
                    frequency = round(data['receipts'] / months_range, 1)
                else:
                    frequency = 0
                
                by_store.append({
                    'name': store_name,
                    'spent': round(float(data['spent']), 2),
                    'itemCount': data['count'],
                    'receiptCount': data['receipts'],
                    'percentage': round(pct, 1),
                    'averageReceipt': round(float(data['spent'] / data['receipts']), 2) if data['receipts'] else 0,
                    'visitFrequency': frequency
                })
            
            by_store.sort(key=lambda x: x['spent'], reverse=True)
            
            # ====== CATEGORY BREAKDOWN ======
            category_data = defaultdict(lambda: {'spent': 0, 'count': 0})
            
            for receipt in receipts:
                for item in receipt.line_items:
                    if item.is_active:
                        # Skip items with "Unknown" or "Unknown Item" name
                        if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                            continue
                        
                        # Skip items with 0.00 price and 0.00 total
                        unit_price = float(item.unit_price or 0)
                        total_price = float(item.total_price or 0)
                        if unit_price == 0.0 and total_price == 0.0:
                            continue
                        
                        category = item.category or 'Uncategorized'
                        category_data[category]['spent'] += item.total_price
                        category_data[category]['count'] += 1
            
            by_category = []
            for category in sorted(category_data.keys()):
                data = category_data[category]
                pct = (data['spent'] / total_spent * 100) if total_spent > 0 else 0
                
                by_category.append({
                    'name': category,
                    'spent': round(float(data['spent']), 2),
                    'itemCount': data['count'],
                    'percentage': round(pct, 1),
                    'averageItem': round(float(data['spent'] / data['count']), 2) if data['count'] > 0 else 0
                })
            
            by_category.sort(key=lambda x: x['spent'], reverse=True)
            
            # ====== TOP ITEMS ======
            item_data = defaultdict(lambda: {'spent': 0, 'count': 0, 'stores': set()})
            
            for receipt in receipts:
                for item in receipt.line_items:
                    if item.is_active:
                        # Skip items with "Unknown" or "Unknown Item" name
                        if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                            continue
                        
                        # Skip items with 0.00 price and 0.00 total
                        unit_price = float(item.unit_price or 0)
                        total_price = float(item.total_price or 0)
                        if unit_price == 0.0 and total_price == 0.0:
                            continue
                        
                        item_name = item.item_name
                        item_data[item_name]['spent'] += item.total_price
                        item_data[item_name]['count'] += item.quantity
                        item_data[item_name]['stores'].add(receipt.location.store_name)
            
            top_items = []
            for item_name in sorted(item_data.keys(), key=lambda x: item_data[x]['spent'], reverse=True)[:15]:
                data = item_data[item_name]
                top_items.append({
                    'name': item_name[:40],  # Truncate for display
                    'spent': round(float(data['spent']), 2),
                    'quantity': round(float(data['count']), 1),
                    'storeCount': len(data['stores']),
                    'averagePrice': round(float(data['spent'] / data['count']), 2) if data['count'] > 0 else 0
                })
            
            # ====== WEEKLY PATTERN ======
            day_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            weekly_data = defaultdict(lambda: {'spent': 0, 'count': 0})
            
            for receipt in receipts:
                if receipt.date:
                    dow = receipt.date.weekday()
                    weekly_data[dow]['spent'] += receipt.total_amount
                    weekly_data[dow]['count'] += 1
            
            weekly_pattern = {}
            for i in range(7):
                weekly_pattern[day_of_week[i]] = {
                    'spent': round(float(weekly_data[i]['spent']), 2),
                    'receiptCount': weekly_data[i]['count'],
                    'averageReceipt': round(float(weekly_data[i]['spent'] / weekly_data[i]['count']), 2) if weekly_data[i]['count'] > 0 else 0
                }
            
            # ====== RECENT ACTIVITY ======
            recent_receipts = sorted(receipts, key=lambda x: x.date or datetime.min, reverse=True)[:10]
            recent = []
            for receipt in recent_receipts:
                item_count = len([i for i in receipt.line_items if i.is_active and 
                                  not (i.item_name and ("Unknown" in i.item_name or "unknown" in i.item_name.lower())) and
                                  not (float(i.unit_price or 0) == 0.0 and float(i.total_price or 0) == 0.0)])
                recent.append({
                    'id': receipt.id,
                    'date': receipt.date.isoformat() if receipt.date else None,
                    'store': receipt.location.store_name,
                    'spent': round(float(receipt.total_amount), 2),
                    'itemCount': item_count
                })
            
            # ====== INSIGHTS ======
            insights = []
            
            # Top spending category
            if by_category:
                top_cat = by_category[0]
                insights.append(f"You spend the most on {top_cat['name']} ({top_cat['percentage']}% of total)")
            
            # Top store
            if by_store:
                top_store = by_store[0]
                insights.append(f"Your top store is {top_store['name']} with ${top_store['spent']} spent")
            
            # Most visited day
            if weekly_pattern:
                most_visited = max(weekly_pattern.items(), key=lambda x: x[1]['receiptCount'])
                insights.append(f"You shop most on {most_visited[0]}s ({most_visited[1]['receiptCount']} visits)")
            
            # Average spending
            if summary['averageTransaction'] > 0:
                insights.append(f"Your average purchase is ${summary['averageTransaction']}")
            
            # Top item
            if top_items:
                top_item = top_items[0]
                insights.append(f"Your most purchased item is {top_item['name']} ({top_item['quantity']} units)")
            
            return jsonify({
                'summary': summary,
                'byMonth': by_month,
                'byStore': by_store,
                'byCategory': by_category,
                'topItems': top_items,
                'topStores': by_store[:5],
                'weeklyPattern': weekly_pattern,
                'recent': recent,
                'insights': insights
            })
        
        finally:
            db_session.close()
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/llm_context', methods=['GET'])
@login_required
def get_llm_context():
    """API endpoint to get the raw context sent to LLM"""
    try:
        user_id = session.get('username')
        question = request.args.get('question', '')
        if not user_id:
            return jsonify({'error': 'Not logged in'})
        
        all_context = get_transactions_from_db(user_id)
        
        if question:
            context, filters = filter_context_by_question(all_context, question)
            table_format = context_to_table(context)
            slim = slim_context(context)
            return jsonify({
                'context': slim, 
                'context_table': table_format,
                'total_transactions': len(all_context),
                'filtered_count': len(context),
                'filters_applied': filters
            })
        else:
            table_format = context_to_table(all_context)
            slim = slim_context(all_context)
            return jsonify({
                'context': slim,
                'context_table': table_format,
                'total_transactions': len(all_context),
                'filtered_count': len(all_context),
                'filters_applied': ['none - showing all data']
            })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    """API endpoint for LLM chat"""
    try:
        data = request.json
        user_id = session.get('username')
        message = data.get('message')
        history = data.get('history', [])  # List of {question, response} dicts
        
        if not message:
            return jsonify({'error': 'Missing message'})
        
        # Load user data from database and filter context based on question
        all_context = get_transactions_from_db(user_id)
        context, filters_applied = filter_context_by_question(all_context, message)
        
        # Use compact table format for LLM context (much more token-efficient than JSON)
        ctx_table = context_to_table(context)
        
        # Build conversation history string (last few exchanges)
        history_str = ""
        if history:
            # Keep only last 3 exchanges to limit token usage
            recent_history = history[-3:]
            history_parts = []
            for h in recent_history:
                if h.get('question') and h.get('response'):
                    history_parts.append(f"User: {h['question']}\nAssistant: {h['response']}")
            if history_parts:
                history_str = "\n\nPrevious conversation:\n" + "\n\n".join(history_parts)
        
        # Check if using agent
        if getattr(llm, 'agent_id', None):
            filter_info = f"(Filtered {len(context)} of {len(all_context)} transactions: {', '.join(filters_applied)})"
            full_content = f"Transaction Data {filter_info}:\n{ctx_table}{history_str}\n\nCurrent question:\n{message}"
            
            res = llm.start_agent_conversation(inputs=[{"role": "user", "content": full_content}])
            
            if isinstance(res, dict) and res.get("error"):
                error_detail = res.get('body', res.get('error'))
                return jsonify({'error': str(error_detail), 'response': f'Sorry, I encountered an error.'})
            
            # Parse agent response - extract text from API response structure
            response_text = None
            if isinstance(res, dict):
                if "outputs" in res and isinstance(res["outputs"], list) and res["outputs"]:
                    out = res["outputs"][0]
                    content = out.get("content") if isinstance(out, dict) else None
                    if isinstance(content, list):
                        texts = [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
                        response_text = "\n".join(t for t in texts if t)
                    elif isinstance(content, str):
                        response_text = content
                elif "results" in res and isinstance(res["results"], list) and res["results"]:
                    first = res["results"][0]
                    contents = first.get("content") or []
                    if isinstance(contents, list):
                        texts = [c.get("text") for c in contents if isinstance(c, dict) and c.get("text")]
                        response_text = "\n".join(t for t in texts if t)
            
            if response_text is None:
                response_text = json.dumps(res) if isinstance(res, dict) else str(res)
            
            return jsonify({
                'response': response_text, 
                'context_sent': True,
                'context_size': len(ctx_table),
                'context_data': ctx_table,
                'filtered_count': len(context),
                'total_count': len(all_context),
                'filters_applied': filters_applied
            })
        else:
            # For non-agent LLM, pass the table context with history
            full_context = ctx_table + history_str if history_str else ctx_table
            response = llm.ask(message, context=full_context)
            return jsonify({
                'response': response, 
                'context_sent': True, 
                'context_size': len(ctx_table),
                'context_data': ctx_table,
                'filtered_count': len(context),
                'total_count': len(all_context),
                'filters_applied': filters_applied
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'response': f'Sorry, I encountered an error: {str(e)}'})


@app.route('/api/save_recommendation', methods=['POST'])
@login_required
def save_recommendation():
    """API endpoint to save a recommendation"""
    try:
        data = request.json
        user_id = session.get('username')
        question = data.get('question')
        response = data.get('response')
        category = data.get('category', 'Other')
        
        # Save to database
        success = save_recommendation_to_db(user_id, question, response, category)
        
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/delete_recommendation', methods=['POST'])
@login_required
def delete_recommendation():
    """API endpoint to delete a recommendation"""
    try:
        data = request.json
        user_id = session.get('username')
        index = data.get('index')
        
        # Delete from database
        success = delete_recommendation_from_db(user_id, index)
        
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/list_files', methods=['GET'])
@login_required
def list_files():
    """API endpoint to list available files in data/raw"""
    try:
        user_id = session.get('username', '')
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        
        if not os.path.exists(raw_dir):
            return jsonify({'files': [], 'error': 'data/raw folder not found'})
        
        # Get list of already imported files for this user from database
        existing = set()
        if user_id:
            existing = set(get_uploaded_files_from_db(user_id))
        
        existing_normalized = {normalize_filename(f) for f in existing}
        
        files = []
        for fname in sorted(os.listdir(raw_dir)):
            path = os.path.join(raw_dir, fname)
            if os.path.isfile(path):
                files.append({
                    'name': fname,
                    'imported': fname in existing or normalize_filename(fname) in existing_normalized
                })
        
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'files': [], 'error': str(e)})


@app.route('/api/import_file', methods=['POST'])
@login_required
def import_single_file():
    """API endpoint to import a single file from data/raw"""
    try:
        data = request.json
        user_id = session.get('username')
        filename = data.get('filename')
        
        if not filename:
            return jsonify({'success': False, 'error': 'Missing filename'})
        
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        
        # Find the actual file - handle encoding issues with special characters
        actual_file = None
        norm_filename = normalize_filename(filename)
        for f in os.listdir(raw_dir):
            if f == filename or normalize_filename(f) == norm_filename:
                actual_file = f
                break
        
        if not actual_file:
            return jsonify({'success': False, 'error': f'File not found: {filename}'})
        
        filepath = os.path.join(raw_dir, actual_file)
        
        # Check if already imported (use actual filename) from database
        existing = set(get_uploaded_files_from_db(user_id))
        if actual_file in existing:
            return jsonify({'success': False, 'error': 'File already imported'})
        
        # Use DataManager to parse the file (but not save to JSON)
        dm.load_user_data(user_id)  # Clear any existing in-memory data
        result = dm.import_file(filepath, user_id)
        
        # Get the parsed transactions and filter by previous import date
        transactions = dm.get_transactions_by_user(user_id)
        
        # Get the latest import date from previously uploaded files with the same base name
        # Example: If uploading Smiths_20260301.json, find the latest Smiths_*.json date already imported
        cutoff_date = get_latest_import_date_for_file(user_id, actual_file)
        if cutoff_date:
            transactions = filter_transactions_by_date(transactions, cutoff_date)
        
        if transactions:
            db_result = add_transactions_to_db(user_id, transactions)
        
        # Record the upload in database
        add_uploaded_file_to_db(user_id, actual_file)
        
        return jsonify({'success': True, 'imported': result.get('imported', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/delete_data', methods=['POST'])
@login_required
def delete_data():
    """API endpoint to delete all user data"""
    try:
        user_id = session.get('username')
        
        # Delete from database
        delete_user_data_from_db(user_id, delete_upload_history=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("    Spend Analyzer Web Application")
    print("=" * 50)
    print("\nStarting Flask development server...")
    print("Open http://127.0.0.1:5000 in your browser\n")
    app.run(debug=True, host='127.0.0.1', port=5000)