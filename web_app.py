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

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

# Import database modules (DB_URL is now defined in db.py)
from spend_analyzer.db import Base, get_engine, get_session, DB_URL
from spend_analyzer.models import User, Location, Receipt, LineItem, Recommendation
from spend_analyzer.migrate import migrate_from_json

# Import API blueprints
from spend_analyzer.api import api_bp


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
        
        # Explicitly delete all line items first
        for item in receipt.line_items:
            db_session.delete(item)
        
        # Then delete the receipt
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

# Register API blueprints
app.register_blueprint(api_bp)


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


# === Settings Page ===
@app.route('/settings')
@login_required
def settings_page():
    """Route for the settings page"""
    user_id = session.get('username', '')
    
    # Get user's current theme preference
    theme = 'default'
    if user_id:
        db_session = get_session(DB_URL)
        try:
            user = db_session.query(User).filter_by(username=user_id).first()
            if user:
                theme = user.theme or 'default'
        except Exception:
            pass
        finally:
            db_session.close()
    
    return render_template('settings.html', user_id=user_id, theme=theme)


# === API Endpoints ===
@app.route('/api/update_theme', methods=['POST'])
@login_required
def update_theme():
    """API endpoint to update user's theme preference"""
    user_id = session.get('username', '')
    data = request.get_json() or {}
    theme = data.get('theme', 'default')
    
    # Validate theme
    valid_themes = ['default', 'cherry-blossoms', 'beach-day', 'falling-leaves', 'winter-forest']
    if theme not in valid_themes:
        theme = 'default'
    
    # Update in database
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=user_id).first()
        if user:
            user.theme = theme
            db_session.commit()
            return jsonify({"success": True, "theme": theme})
    except Exception as e:
        db_session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db_session.close()
    
    return jsonify({"success": False, "error": "User not found"}), 404


@app.route('/api/delete_data', methods=['POST'])
@login_required
def delete_user_data():
    """API endpoint to delete all user data"""
    import os
    user_id = session.get('username', '')
    
    db_session = get_session(DB_URL)
    try:
        # Get user to delete their data
        user = db_session.query(User).filter_by(username=user_id).first()
        if user:
            # Get all receipts for this user
            receipts = db_session.query(Receipt).filter_by(user_id=user.id).all()
            
            # Explicitly delete all line items first
            for receipt in receipts:
                for item in receipt.line_items:
                    db_session.delete(item)
            
            # Then delete all receipts
            db_session.query(Receipt).filter_by(user_id=user.id).delete()
            
            # Delete recommendations
            db_session.query(Recommendation).filter_by(user_id=user.id).delete()
            db_session.commit()
            
            # Delete upload history JSON files
            from spend_analyzer.data_manager import DataManager
            dm = DataManager()
            dm.delete_user_data(user_id, delete_upload_history=True)
            
            return jsonify({"success": True})
    except Exception as e:
        db_session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db_session.close()
    
    return jsonify({"success": False, "error": "User not found"}), 404


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("    Spend Analyzer Web Application")
    print("=" * 50)
    print("\nStarting Flask development server...")
    print("Open http://127.0.0.1:5000 in your browser\n")
    app.run(debug=True, host='127.0.0.1', port=5000)