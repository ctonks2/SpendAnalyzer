"""
Flask Web Application for Spend Analyzer
A simple web interface for managing receipts and getting AI spending insights.
"""

from flask import Flask, render_template, request, jsonify
import os
import json
import unicodedata
import re
from datetime import datetime

# Import existing modules
from spend_analyzer.data_manager import DataManager
from spend_analyzer.llm_client import LLMClient
from spend_analyzer.llm_menu import LLMMenu


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


app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize shared instances
dm = DataManager()
llm = LLMClient()
llm_menu = LLMMenu(llm, dm)

def normalize_filename(s):
    """Normalize unicode and replace common apostrophe variants for filename comparison."""
    s = unicodedata.normalize('NFC', s)
    return s.replace(''', "'").replace(''', "'").replace('`', "'")


@app.route('/')
def index():
    """Main route - renders the single-page application"""
    user_id = request.args.get('user_id', '')
    
    transactions = []
    total_spent = 0
    store_count = 0
    recommendations = []
    
    if user_id:
        dm.load_user_data(user_id)
        transactions = dm.get_transactions_by_user(user_id)
        
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
        
        # Load recommendations
        recommendations, _ = llm_menu.load_recommendations(user_id)
    
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


@app.route('/api/add_receipt', methods=['POST'])
def add_receipt():
    """API endpoint to add a new receipt"""
    try:
        data = request.json
        user_id = data.get('user_id')
        store_number = data.get('store_number')
        store_name = data.get('store_name', 'unknown')
        date_str = data.get('date')
        items = data.get('items', [])
        
        if not user_id or not items:
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        dm.load_user_data(user_id)
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
        
        result = dm.add_transactions(user_id, transactions)
        return jsonify({'success': True, 'imported': result.get('imported', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/llm_context', methods=['GET'])
def get_llm_context():
    """API endpoint to get the raw context sent to LLM"""
    try:
        user_id = request.args.get('user_id')
        question = request.args.get('question', '')
        if not user_id:
            return jsonify({'error': 'Missing user_id'})
        
        dm.load_user_data(user_id)
        all_context = dm.get_transactions_by_user(user_id)
        
        if question:
            context, filters = filter_context_by_question(all_context, question)
            slim = slim_context(context)
            return jsonify({
                'context': slim, 
                'total_transactions': len(all_context),
                'filtered_count': len(context),
                'filters_applied': filters
            })
        else:
            slim = slim_context(all_context)
            return jsonify({
                'context': slim,
                'total_transactions': len(all_context),
                'filtered_count': len(all_context),
                'filters_applied': ['none - showing all data']
            })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/chat', methods=['POST'])
def chat():
    """API endpoint for LLM chat"""
    try:
        data = request.json
        user_id = data.get('user_id')
        message = data.get('message')
        
        if not user_id or not message:
            return jsonify({'error': 'Missing user_id or message'})
        
        # Load user data and filter context based on question
        dm.load_user_data(user_id)
        all_context = dm.get_transactions_by_user(user_id)
        context, filters_applied = filter_context_by_question(all_context, message)
        slim = slim_context(context)
        
        # Check if using agent
        if getattr(llm, 'agent_id', None):
            ctx_snippet = json.dumps(slim, default=str)
            filter_info = f"(Filtered {len(context)} of {len(all_context)} transactions: {', '.join(filters_applied)})"
            full_content = f"Context {filter_info}:\n{ctx_snippet}\n\nMy question:\n{message}"
            
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
                'context_size': len(ctx_snippet),
                'filtered_count': len(context)
            })
        else:
            response = llm.ask(message, context=slim)
            return jsonify({'response': response, 'context_sent': True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'response': f'Sorry, I encountered an error: {str(e)}'})


@app.route('/api/save_recommendation', methods=['POST'])
def save_recommendation():
    """API endpoint to save a recommendation"""
    try:
        data = request.json
        user_id = data.get('user_id')
        question = data.get('question')
        response = data.get('response')
        category = data.get('category', 'Other')
        
        rec_file = llm_menu._rec_file(user_id)
        recommendation = {
            "user_id": user_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "category": category,
            "question": question,
            "response": response,
            "saved_at": datetime.now().isoformat()
        }
        
        recs, _ = llm_menu.load_recommendations(user_id)
        recs.append(recommendation)
        
        with open(rec_file, "w", encoding="utf-8") as f:
            json.dump(recs, f, indent=2, default=str)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/delete_recommendation', methods=['POST'])
def delete_recommendation():
    """API endpoint to delete a recommendation"""
    try:
        data = request.json
        user_id = data.get('user_id')
        index = data.get('index')
        
        recs, rec_file = llm_menu.load_recommendations(user_id)
        if 0 <= index < len(recs):
            recs.pop(index)
            with open(rec_file, "w", encoding="utf-8") as f:
                json.dump(recs, f, indent=2, default=str)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/list_files', methods=['GET'])
def list_files():
    """API endpoint to list available files in data/raw"""
    try:
        user_id = request.args.get('user_id', '')
        raw_dir = os.path.join(os.getcwd(), "data", "raw")
        
        if not os.path.exists(raw_dir):
            return jsonify({'files': [], 'error': 'data/raw folder not found'})
        
        # Get list of already imported files for this user
        existing = set()
        if user_id:
            existing = set(dm.get_uploaded_filenames(user_id))
        
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
def import_single_file():
    """API endpoint to import a single file from data/raw"""
    try:
        data = request.json
        user_id = data.get('user_id')
        filename = data.get('filename')
        
        if not user_id or not filename:
            return jsonify({'success': False, 'error': 'Missing user_id or filename'})
        
        dm.load_user_data(user_id)
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
        
        # Check if already imported (use actual filename)
        existing = set(dm.get_uploaded_filenames(user_id))
        if actual_file in existing:
            return jsonify({'success': False, 'error': 'File already imported'})
        
        result = dm.import_file(filepath, user_id)
        dm.add_uploaded_filename(user_id, actual_file)
        dm.save_user_data(user_id)
        
        return jsonify({'success': True, 'imported': result.get('imported', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/delete_data', methods=['POST'])
def delete_data():
    """API endpoint to delete all user data"""
    try:
        data = request.json
        user_id = data.get('user_id')
        
        dm.delete_user_data(user_id, delete_upload_history=True)
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
