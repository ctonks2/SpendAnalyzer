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

# Import existing modules
from spend_analyzer.data_manager import DataManager
from spend_analyzer.llm_client import LLMClient
from spend_analyzer.llm_menu import LLMMenu

# Import database modules
from spend_analyzer.db import Base, get_engine, get_session
from spend_analyzer.models import User, Location, Receipt, LineItem, UserHistory, Recommendation
from spend_analyzer.migrate import migrate_from_json


# Database URL - using spend_data.db for new SQLAlchemy-managed data
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
    """
    db_session = get_session(DB_URL)
    try:
        user = db_session.query(User).filter_by(username=username).first()
        if not user:
            return []
        
        transactions = []
        for receipt in user.receipts:
            for item in receipt.line_items:
                tx = {
                    "transaction_id": f"tx_{item.id}",
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
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

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
    """Main route - renders the single-page application"""
    user_id = session.get('username', '')
    user = get_current_user()
    
    transactions = []
    total_spent = 0
    store_count = 0
    recommendations = []
    
    if user_id:
        transactions = get_transactions_from_db(user_id)
        
        # Calculate stats (exclude RECEIPT_TOTAL to avoid double-counting)
        stores = set()
        for tx in transactions:
            if tx.get('item_name') == 'RECEIPT_TOTAL':
                continue  # Skip receipt totals - they duplicate item totals
            try:
                total_spent += float(tx.get('total_price') or 0)
            except:
                pass
            if tx.get('store'):
                stores.add(tx.get('store'))
        store_count = len(stores)
        
        # Load recommendations from database
        recommendations = get_recommendations_from_db(user_id)
    
    return render_template(
        'index.html',
        user_id=user_id,
        transactions=transactions,
        transaction_count=len(transactions),
        total_spent=total_spent,
        store_count=store_count,
        recommendations=recommendations,
        rec_count=len(recommendations)
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
            
            # Add discount line item if there's a discount
            if item_discount > 0:
                transactions.append({
                    'user_id': user_id,
                    'item_name': f"DISCOUNT ({item.get('name')})",
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
        
        result = add_transactions_to_db(user_id, transactions)
        return jsonify({'success': True, 'imported': result.get('imported', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


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
        
        # Get the parsed transactions and save to database
        transactions = dm.get_transactions_by_user(user_id)
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