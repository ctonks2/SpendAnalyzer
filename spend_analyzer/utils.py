"""Utility functions for Spend Analyzer"""

from functools import wraps
from flask import session, jsonify
from contextlib import contextmanager


# ============ AUTHENTICATION ============

def login_required(f):
    """
    Decorator to require login for routes/API endpoints.
    
    Checks if 'user_id' is in the session. If not, returns 401 Unauthorized.
    
    Usage:
        @app.route('/protected')
        @login_required
        def protected_route():
            user_id = session.get('user_id')
            return {'message': f'Hello {user_id}'}
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ============ DATABASE ============

@contextmanager
def get_db_session_context(DB_URL):
    """
    Context manager for database sessions.
    
    Automatically handles session creation and cleanup.
    
    Usage:
        with get_db_session_context(DB_URL) as db_session:
            user = db_session.query(User).first()
    """
    from .db import get_session
    db_session = get_session(DB_URL)
    try:
        yield db_session
    finally:
        db_session.close()


# ============ DATA VALIDATION ============

def is_valid_line_item(item):
    """
    Check if a line item should be included in analysis/display.
    
    Filters out:
    - Items with "Unknown" or "unknown" in the name (data quality issues)
    - Items with zero unit price AND zero total price (placeholder items)
    
    Args:
        item: A LineItem object with attributes: item_name, unit_price, total_price
        
    Returns:
        bool: True if the item should be included, False otherwise
    """
    # Skip items with "Unknown" or "Unknown Item" name
    if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
        return False
    
    # Skip items with 0.00 price and 0.00 total
    unit_price = float(item.unit_price or 0)
    total_price = float(item.total_price or 0)
    if unit_price == 0.0 and total_price == 0.0:
        return False
    
    return True


def filter_valid_line_items(items):
    """
    Filter a list of line items to only include valid ones.
    
    Args:
        items: List of LineItem objects
        
    Returns:
        list: Filtered list of valid LineItem objects
    """
    return [item for item in items if is_valid_line_item(item)]


def skip_receipt_summary_items(item):
    """
    Check if an item is a receipt summary/metadata item that should be skipped.
    
    Filters out special items like:
    - RECEIPT_TOTAL (receipt total markers)
    - DISCOUNT items (legacy support)
    
    Args:
        item: A LineItem or similar object with item_name attribute
        
    Returns:
        bool: True if the item should be skipped, False otherwise
    """
    if not item:
        return True
    
    item_name = getattr(item, 'item_name', None) or (item.get('item_name') if isinstance(item, dict) else None)
    if not item_name:
        return True
    
    item_name_str = str(item_name).strip().upper()
    
    # Skip RECEIPT_TOTAL and DISCOUNT items (legacy support)
    return item_name_str in ('RECEIPT_TOTAL', 'DISCOUNT')
