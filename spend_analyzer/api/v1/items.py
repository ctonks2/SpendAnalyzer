"""
API v1 Items endpoints
Provides RESTful access to line items with versioning.
"""

from flask import Blueprint, jsonify, session
from functools import wraps

# Create blueprint for v1 items endpoints
# Note: url_prefix handled by parent v1_bp, so just use relative route paths
items_bp = Blueprint('api_v1_items', __name__, url_prefix='/items')


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function


@items_bp.route('', methods=['GET'])
@login_required
def get_all_items():
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
    # Import here to avoid circular imports
    from spend_analyzer.db import get_transactions_from_db
    
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


@items_bp.route('/<int:item_id>', methods=['GET'])
@login_required
def get_single_item(item_id):
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
    # Import here to avoid circular imports
    from spend_analyzer.db import get_transactions_from_db
    
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
