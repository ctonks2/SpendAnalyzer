"""
Legacy API Endpoints (/api/legacy/)
DEPRECATED: These endpoints are maintained for backward compatibility only.

These endpoints have been deprecated in favor of the v1 API:
- /api/legacy/list_files  ->  Replaced by web UI at /import
- /api/legacy/import_file ->  Replaced by web UI at /import

Many endpoints were disabled as they required non-existent database functions.
"""

from flask import Blueprint, jsonify, session, request
import os

from ..utils import login_required, get_db_session_context

legacy_api_bp = Blueprint('api_legacy', __name__, url_prefix='/api/legacy')


# ====== FILE MANAGEMENT ======

# ====== FILE MANAGEMENT ======
# Note: Other endpoints (receipt, lineitem, recommendations) have been disabled
# as they required database functions that don't exist in the current db module.
# They will be reimplemented when the database layer is refactored.


@legacy_api_bp.route('/list_files', methods=['GET'])
@login_required
def list_files():
    """List all available files in data/raw, exclude ones already uploaded by user"""
    try:
        user_id = session.get('username', '')
        # Get the project root (2 levels up from this module: spend_analyzer/api/legacy.py)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        raw_dir = os.path.join(project_root, "data", "raw")
        
        if not os.path.exists(raw_dir):
            return jsonify({'files': [], 'error': 'data/raw folder not found'})
        
        # Get list of files already uploaded by this user
        from spend_analyzer.data_manager import DataManager
        dm = DataManager()
        dm.load_user_data(user_id)
        already_uploaded = set(dm.get_uploaded_filenames(user_id))
        
        # List files in data/raw, excluding system files
        # Only include actual data files (json, xlsx, xls, csv, etc)
        valid_extensions = {'.json', '.xlsx', '.xls', '.csv', '.xml', '.pdf'}
        excluded_files = {'.gitkeep', 'deployment.txt'}
        
        files = []
        for fname in sorted(os.listdir(raw_dir)):
            path = os.path.join(raw_dir, fname)
            if os.path.isfile(path):
                # Skip system files and files without data extensions
                if fname in excluded_files or not any(fname.lower().endswith(ext) for ext in valid_extensions):
                    continue
                files.append({
                    'name': fname,
                    'imported': fname in already_uploaded  # Mark if already imported by this user
                })
        
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'files': [], 'error': str(e)})


@legacy_api_bp.route('/import_file', methods=['POST'])
@login_required
def import_single_file():
    """Import a single file from data/raw and save to database"""
    from spend_analyzer.data_manager import DataManager
    from spend_analyzer.db import get_session, DB_URL
    from spend_analyzer.models import User, Location, Receipt, LineItem
    
    try:
        data = request.json
        user_id = session.get('username')
        filename = data.get('filename')
        
        if not filename:
            return jsonify({'success': False, 'error': 'Missing filename'})
        
        # Get the project root (2 levels up: spend_analyzer/api/legacy.py -> project root)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        raw_dir = os.path.join(project_root, "data", "raw")
        
        # Find the actual file
        actual_file = None
        for f in os.listdir(raw_dir):
            if f == filename:
                actual_file = f
                break
        
        if not actual_file:
            return jsonify({'success': False, 'error': f'File not found: {filename}'})
        
        filepath = os.path.join(raw_dir, actual_file)
        
        # Import file using DataManager
        dm = DataManager()
        dm.load_user_data(user_id)
        
        # Check if already imported
        existing = set(dm.get_uploaded_filenames(user_id))
        if actual_file in existing:
            return jsonify({'success': False, 'error': 'File already imported'})
        
        # Import the file (saves to JSON)
        result = dm.import_file(filepath, user_id)
        imported_count = result.get('imported', 0)
        
        dm.save_user_data(user_id)
        
        # Now save to database
        try:
            with get_db_session_context(DB_URL) as db_session:
                # Get or create user in database
                db_user = db_session.query(User).filter_by(username=user_id).first()
                if not db_user:
                    db_user = User(username=user_id)
                    db_session.add(db_user)
                    db_session.flush()
                
                # Only use transactions (rest of code properly indented)
                # Don't reload from JSON which would include all previous imports
                transactions = dm.transactions
                
                # Save each transaction to database
                saved_count = 0
                receipt_ids_touched = set()
                for tx in transactions:
                    if tx.get('user_id') != user_id:
                        continue
                    
                    # Skip receipt total markers
                    if tx.get('item_name') == 'RECEIPT_TOTAL':
                        continue
                    
                    # Skip invalid items (no item_name)
                    item_name = tx.get('item_name', '').strip() if tx.get('item_name') else ''
                    if not item_name:
                        continue
                    
                    # Skip items with no valid total price
                    total_price = float(tx.get('total_price', 0) or tx.get('total_after', 0) or 0)
                    if total_price == 0 and float(tx.get('unit_price', 0) or 0) == 0:
                        continue
                    
                    # Get or create location
                    store_number = tx.get('store', 'Unknown')
                    store_name = tx.get('source', 'Unknown Store')
                    location = db_session.query(Location).filter_by(
                        store_number=store_number
                    ).first()
                    if not location:
                        location = Location(store_number=store_number, store_name=store_name)
                        db_session.add(location)
                        db_session.flush()
                    
                    # Create receipt if needed
                    orderno = tx.get('orderno', f"{store_number}.{tx.get('date')}")
                    
                    # Parse date to ensure it's just a date, not datetime
                    date_str = tx.get('date', '2026-01-01')
                    from datetime import datetime as dt
                    if isinstance(date_str, str):
                        try:
                            purchase_date = dt.strptime(date_str, '%Y-%m-%d').date()
                        except:
                            from datetime import date
                            purchase_date = date.today()
                    else:
                        from datetime import date
                        purchase_date = date.today()
                    
                    receipt = db_session.query(Receipt).filter_by(
                        user_id=db_user.id,
                        location_id=location.id,
                        order_number=orderno
                    ).first()
                    if not receipt:
                        receipt = Receipt(
                            user_id=db_user.id,
                            location_id=location.id,
                            order_number=orderno,
                            date=purchase_date,
                            is_active=True,
                            total_amount=0.0
                        )
                        db_session.add(receipt)
                        db_session.flush()
                    
                    # Create line item (note: no discount_amount field, total_price is final)
                    line_item = LineItem(
                        receipt_id=receipt.id,
                        item_name=item_name, 
                        unit_price=float(tx.get('unit_price', 0) or 0),
                        quantity=float(tx.get('quantity', 1) or 1),
                        total_price=total_price, 
                        category=tx.get('category'),
                        product_upc=tx.get('upc'),
                        is_active=True
                    )
                    db_session.add(line_item)
                    saved_count += 1
                    receipt_ids_touched.add(receipt.id)
                
                # Update receipt totals based on line items
                for receipt_id in receipt_ids_touched:
                    receipt = db_session.query(Receipt).filter_by(id=receipt_id).first()
                    if receipt:
                        total = sum(item.total_price for item in receipt.line_items if item.is_active)
                        receipt.total_amount = round(float(total), 2)
                
                # Commit all changes
                db_session.commit()
                
                # Only mark as imported AFTER successful database save
                dm.add_uploaded_filename(user_id, actual_file)
                
                return jsonify({
                    'success': True, 
                    'imported': imported_count,
                    'saved_to_db': saved_count
                })
        
        except Exception as db_error:
            return jsonify({
                'success': False, 
                'error': f'Database error: {str(db_error)}'
            })
    except Exception as e:                          # ← add this
        return jsonify({'success': False, 'error': f'Unexpected error: {str(e)}'})    
