"""
Legacy API Endpoints (unversioned /api/)
These endpoints are maintained for backward compatibility but v1 is recommended for new code.
"""

from flask import Blueprint, jsonify, session, request
from functools import wraps
import json
import os

legacy_api_bp = Blueprint('api_legacy', __name__, url_prefix='/api')


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ====== RECEIPT MANAGEMENT ======

@legacy_api_bp.route('/receipt/<int:receipt_id>/delete', methods=['POST'])
@login_required
def delete_receipt(receipt_id):
    """Delete a receipt (soft or hard delete)"""
    from spend_analyzer.db import (
        get_session, DB_URL, soft_delete_receipt, hard_delete_receipt
    )
    
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


@legacy_api_bp.route('/lineitem/<int:line_item_id>/delete', methods=['POST'])
@login_required
def delete_line_item(line_item_id):
    """Delete a line item (soft or hard delete)"""
    from spend_analyzer.db import soft_delete_line_item, hard_delete_line_item
    
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


@legacy_api_bp.route('/add_receipt', methods=['POST'])
@login_required
def add_receipt():
    """Add a new receipt via API"""
    from spend_analyzer.db import add_transactions_to_db
    
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
        
        # Add receipt total
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


# ====== USER SETTINGS ======

@legacy_api_bp.route('/update_theme', methods=['POST'])
@login_required
def update_theme():
    """Update user's theme preference"""
    from spend_analyzer.db import get_session, DB_URL
    from spend_analyzer.models import User
    
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


# ====== RECOMMENDATIONS ======

@legacy_api_bp.route('/save_recommendation', methods=['POST'])
@login_required
def save_recommendation():
    """Save a recommendation"""
    from spend_analyzer.db import save_recommendation_to_db
    
    try:
        data = request.json
        user_id = session.get('username')
        question = data.get('question')
        response = data.get('response')
        category = data.get('category', 'Other')
        
        success = save_recommendation_to_db(user_id, question, response, category)
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@legacy_api_bp.route('/delete_recommendation', methods=['POST'])
@login_required
def delete_recommendation():
    """Delete a recommendation"""
    from spend_analyzer.db import delete_recommendation_from_db
    
    try:
        data = request.json
        user_id = session.get('username')
        index = data.get('index')
        
        success = delete_recommendation_from_db(user_id, index)
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ====== FILE MANAGEMENT ======

@legacy_api_bp.route('/list_files', methods=['GET'])
@login_required
def list_files():
    """List available files in data/raw"""
    from spend_analyzer.db import (
        get_uploaded_files_from_db, normalize_filename
    )
    
    try:
        user_id = session.get('username', '')
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        
        if not os.path.exists(raw_dir):
            return jsonify({'files': [], 'error': 'data/raw folder not found'})
        
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


@legacy_api_bp.route('/import_file', methods=['POST'])
@login_required
def import_single_file():
    """Import a single file from data/raw"""
    from spend_analyzer.db import (
        normalize_filename, get_uploaded_files_from_db,
        add_uploaded_file_to_db, add_transactions_to_db,
        get_latest_import_date_for_file, filter_transactions_by_date
    )
    from spend_analyzer.data_manager import DataManager
    
    try:
        data = request.json
        user_id = session.get('username')
        filename = data.get('filename')
        
        if not filename:
            return jsonify({'success': False, 'error': 'Missing filename'})
        
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        
        # Find the actual file
        actual_file = None
        norm_filename = normalize_filename(filename)
        for f in os.listdir(raw_dir):
            if f == filename or normalize_filename(f) == norm_filename:
                actual_file = f
                break
        
        if not actual_file:
            return jsonify({'success': False, 'error': f'File not found: {filename}'})
        
        filepath = os.path.join(raw_dir, actual_file)
        
        # Check if already imported
        existing = set(get_uploaded_files_from_db(user_id))
        if actual_file in existing:
            return jsonify({'success': False, 'error': 'File already imported'})
        
        # Import file
        dm = DataManager()
        dm.load_user_data(user_id)
        result = dm.import_file(filepath, user_id)
        
        transactions = dm.get_transactions_by_user(user_id)
        
        # Filter by previous import date
        cutoff_date = get_latest_import_date_for_file(user_id, actual_file)
        if cutoff_date:
            transactions = filter_transactions_by_date(transactions, cutoff_date)
        
        if transactions:
            db_result = add_transactions_to_db(user_id, transactions)
        
        add_uploaded_file_to_db(user_id, actual_file)
        
        return jsonify({'success': True, 'imported': result.get('imported', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@legacy_api_bp.route('/delete_data', methods=['POST'])
@login_required
def delete_data():
    """Delete all user data"""
    from spend_analyzer.db import delete_user_data_from_db
    
    try:
        user_id = session.get('username')
        delete_user_data_from_db(user_id, delete_upload_history=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
