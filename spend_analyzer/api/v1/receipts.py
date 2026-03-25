"""
API v1 Receipts endpoints
Provides RESTful access to receipts with versioning.
"""

from flask import Blueprint, jsonify, session, request
from functools import wraps
from datetime import datetime as dt

# Create blueprint for v1 receipt endpoints
receipts_bp = Blueprint('api_v1_receipts', __name__, url_prefix='/receipts')


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function


@receipts_bp.route('/<int:receipt_id>/delete', methods=['POST'])
@login_required
def delete_receipt(receipt_id):
    """
    Delete a receipt (soft or hard delete).
    
    Expected JSON body:
        {
            "delete_type": "soft" or "hard"
        }
    
    Returns:
        HTTP 200: Success with {'success': true, 'message': '...'}
        HTTP 400: Invalid delete_type
        HTTP 404: Receipt not found
        HTTP 401: Unauthorized
        HTTP 500: Server error
    """
    from spend_analyzer.db import get_session, DB_URL
    from spend_analyzer.models import User, Receipt
    
    try:
        user_id = session.get('username', '')
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': 'No JSON body provided'}), 400
        
        delete_type = data.get('delete_type', 'soft')
        
        if delete_type not in ('soft', 'hard'):
            return jsonify({'success': False, 'message': 'Invalid delete_type. Must be "soft" or "hard"'}), 400
        
        # Get database session
        db_session = get_session(DB_URL)
        
        try:
            # Verify user exists
            user = db_session.query(User).filter_by(username=user_id).first()
            if not user:
                return jsonify({'success': False, 'message': 'User not found'}), 404
            
            # Get receipt
            receipt = db_session.query(Receipt).filter_by(id=receipt_id, user_id=user.id).first()
            if not receipt:
                return jsonify({'success': False, 'message': 'Receipt not found'}), 404
            
            # Perform soft or hard delete
            if delete_type == 'soft':
                receipt.is_active = False
                receipt.updated_at = dt.utcnow()
                
                # Soft delete all line items
                for item in receipt.line_items:
                    item.is_active = False
                    item.updated_at = dt.utcnow()
                
                db_session.commit()
                return jsonify({'success': True, 'message': 'Receipt soft deleted successfully'}), 200
            
            else:  # hard delete
                # Explicitly delete all line items first
                for item in receipt.line_items:
                    db_session.delete(item)
                
                # Then delete the receipt
                db_session.delete(receipt)
                db_session.commit()
                return jsonify({'success': True, 'message': 'Receipt permanently deleted'}), 200
        
        except Exception as e:
            db_session.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500
        
        finally:
            db_session.close()
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
