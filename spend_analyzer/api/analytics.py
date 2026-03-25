"""
Analytics API Blueprint
Provides detailed spending analytics and insights.
"""

from flask import Blueprint, jsonify, session, request
from functools import wraps
from collections import defaultdict
from datetime import datetime

analytics_bp = Blueprint('api_analytics', __name__, url_prefix='/api')


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function


@analytics_bp.route('/analytics', methods=['GET'])
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
    from spend_analyzer.db import get_session, DB_URL
    from spend_analyzer.models import User
    
    try:
        user_id = session.get('username')
        db_session = get_session(DB_URL)
        
        try:
            user = db_session.query(User).filter_by(username=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
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
                    # Calculate actual receipt total from line items (don't rely on stored total_amount)
                    receipt_total = sum(item.total_price for item in receipt.line_items if item.is_active)
                    transaction_dates[receipt.date] += receipt_total
                
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
                    # Calculate actual receipt total from line items
                    receipt_total = sum(item.total_price for item in receipt.line_items if item.is_active)
                    monthly_data[month_key]['spent'] += receipt_total
                    
                    for item in receipt.line_items:
                        if item.is_active:
                            if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                                continue
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
                # Calculate actual receipt total from line items
                receipt_total = sum(item.total_price for item in receipt.line_items if item.is_active)
                store_data[store_name]['spent'] += receipt_total
                if receipt.date:
                    store_data[store_name]['dates'].append(receipt.date)
                
                for item in receipt.line_items:
                    if item.is_active:
                        if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                            continue
                        unit_price = float(item.unit_price or 0)
                        total_price = float(item.total_price or 0)
                        if unit_price == 0.0 and total_price == 0.0:
                            continue
                        store_data[store_name]['count'] += 1
            
            by_store = []
            for store_name in sorted(store_data.keys()):
                data = store_data[store_name]
                pct = (data['spent'] / total_spent * 100) if total_spent > 0 else 0
                
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
                        if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                            continue
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
                        if item.item_name and ("Unknown" in item.item_name or "unknown" in item.item_name.lower()):
                            continue
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
                    'name': item_name[:40],
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
                    # Calculate actual receipt total from line items
                    receipt_total = sum(item.total_price for item in receipt.line_items if item.is_active)
                    weekly_data[dow]['spent'] += receipt_total
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
                # Calculate actual receipt total from line items
                receipt_total = sum(item.total_price for item in receipt.line_items if item.is_active)
                recent.append({
                    'id': receipt.id,
                    'date': receipt.date.isoformat() if receipt.date else None,
                    'store': receipt.location.store_name,
                    'spent': round(float(receipt_total), 2),
                    'itemCount': item_count
                })
            
            # ====== INSIGHTS ======
            insights = []
            if by_category:
                top_cat = by_category[0]
                insights.append(f"You spend the most on {top_cat['name']} ({top_cat['percentage']}% of total)")
            if by_store:
                top_store = by_store[0]
                insights.append(f"Your top store is {top_store['name']} with ${top_store['spent']} spent")
            if weekly_pattern:
                most_visited = max(weekly_pattern.items(), key=lambda x: x[1]['receiptCount'])
                insights.append(f"You shop most on {most_visited[0]}s ({most_visited[1]['receiptCount']} visits)")
            if summary['averageTransaction'] > 0:
                insights.append(f"Your average purchase is ${summary['averageTransaction']}")
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


@analytics_bp.route('/llm_context', methods=['GET'])
@login_required
def get_llm_context():
    """Get the raw context sent to LLM"""
    from spend_analyzer.db import (
        get_transactions_from_db, filter_context_by_question,
        context_to_table, slim_context
    )
    
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
