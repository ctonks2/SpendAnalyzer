"""
Chat/LLM API Blueprint (v1)
Provides AI chat and recommendation endpoints.
"""

from flask import Blueprint, jsonify, session, request
import json
from datetime import datetime, timedelta

from ..utils import login_required

chat_bp = Blueprint('api_v1_chat', __name__, url_prefix='/chat')


def _get_data_reduction_suggestions(all_transactions, current_context):
    """Generate user-friendly suggestions for reducing data/token usage."""
    suggestions = []
    
    if not all_transactions:
        return "filtering your data"
    
    # Analyze store distribution
    stores = {}
    for t in all_transactions:
        store = t.get('store', 'Unknown')
        stores[store] = stores.get(store, 0) + 1
    
    if stores and len(stores) > 3:
        top_store = max(stores.items(), key=lambda x: x[1])[0]
        other_stores = [s for s in stores.keys() if s != top_store][:2]
        suggestions.append(f"specifying only from '{top_store}' store" if len(current_context) > 100 else f"excluding '{top_store}' and focusing on fewer stores")
    
    # Analyze date distribution
    if all_transactions:
        dates = [datetime.fromisoformat(t.get('date', datetime.now().isoformat())) for t in all_transactions if t.get('date')]
        if dates:
            date_range = (max(dates) - min(dates)).days
            if date_range > 365:
                suggestions.append("looking at a specific year (e.g., 'Compare 2024 versus 2025')")
            elif date_range > 90:
                suggestions.append("looking at a specific month or quarter")
    
    # Analyze category distribution  
    categories = set(t.get('category', 'Uncategorized') for t in all_transactions)
    if len(categories) > 5:
        suggestions.append("focusing on specific spending categories")
    
    # Fallback
    if not suggestions:
        suggestions.append("using fewer transactions in your query")
    
    # Return the first 2 suggestions
    if len(suggestions) > 1:
        return " or ".join(suggestions[:2])
    return suggestions[0]


@chat_bp.route('', methods=['POST'])
@login_required
def chat():
    """
    API endpoint for LLM chat with spending data context.
    Accepts chat message and optional conversation history.
    """
    # Import helper functions from parent scope (web_app.py)
    # These need to be imported locally to avoid circular imports
    try:
        from web_app import get_transactions_from_db, filter_context_by_question, context_to_table
    except ImportError:
        # Fallback: define minimal inline versions if web_app import fails
        def get_transactions_from_db(username):
            from ..db import DB_URL
            from ..models import User
            from ..utils import get_db_session_context
            with get_db_session_context(DB_URL) as db_session:
                user = db_session.query(User).filter_by(username=username).first()
                if not user:
                    return []
                transactions = []
                for receipt in user.receipts:
                    if not receipt.is_active:
                        continue
                    for item in receipt.line_items:
                        if not item.is_active:
                            continue
                        transactions.append({
                            'date': receipt.date.isoformat(),
                            'store': receipt.location.store_name,
                            'item_name': item.item_name,
                            'category': item.category or 'Uncategorized',
                            'total_price': float(item.total_price)
                        })
                return transactions
        
        def filter_context_by_question(transactions, question):
            return transactions, []
        
        def context_to_table(transactions):
            if not transactions:
                return "No transactions found."
            lines = ["Date | Store | Item | Category | Price"]
            for t in transactions:
                lines.append(f"{t['date']} | {t['store']} | {t['item_name']} | {t['category']} | ${t['total_price']:.2f}")
            return "\n".join(lines)
    
    from spend_analyzer.llm_client import LLMClient
    
    try:
        data = request.json
        user_id = session.get('username')
        message = data.get('message')
        
        if not message:
            return jsonify({'error': 'Missing message'})
        
        # Load user data and filter by question
        all_context = get_transactions_from_db(user_id)
        context, filters_applied = filter_context_by_question(all_context, message)
        
        # Use compact table format
        ctx_table = context_to_table(context)
        
        # Get LLM instance
        llm = LLMClient()
        
        # Check if using agent
        if getattr(llm, 'agent_id', None):
            filter_info = f"(Filtered {len(context)} of {len(all_context)} transactions: {', '.join(filters_applied)})"
            full_content = f"Transaction Data {filter_info}:\n{ctx_table}\n\nQuestion:\n{message}"
            
            # Log request details
            print(f"\n[CHAT REQUEST]")
            print(f"  Agent ID: {llm.agent_id}")
            print(f"  Content length: {len(full_content)} chars")
            print(f"  Transaction count: {len(context)} of {len(all_context)}")
            
            res = llm.start_agent_conversation(inputs=[{"role": "user", "content": full_content}])
            
            # Log full response
            print(f"[AGENT RESPONSE] {json.dumps(res, default=str)[:500]}")
            
            if isinstance(res, dict) and res.get("error"):
                error_detail = res.get('body', res.get('error'))
                error_str = str(error_detail).lower()
                
                # Log the actual error for debugging
                print(f"[LLM ERROR DETECTED] {error_str}")
                
                # Check for token limit errors with expanded keyword list
                token_keywords = ['token', 'length', 'too large', 'overflow', 'exceed', 'max_tokens', 'context_length', 'input_too_long', '413', '400']
                if any(keyword in error_str for keyword in token_keywords):
                    suggestion = _get_data_reduction_suggestions(all_context, context)
                    user_message = f'Too much data was sent to the AI. Please try again by {suggestion}'
                    return jsonify({'error': str(error_detail), 'response': user_message, 'is_token_error': True})
                
                return jsonify({'error': str(error_detail), 'response': f'LLM Error: {str(error_detail)}'})
            
            # Parse agent response
            response_text = None
            if isinstance(res, dict):
                if "outputs" in res and isinstance(res["outputs"], list) and res["outputs"]:
                    out = res["outputs"][0]
                    content = out.get("content") if isinstance(out, dict) else None
                    if isinstance(content, list):
                        texts = []
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            # Handle text type blocks
                            if c.get("type") == "text" and c.get("text"):
                                texts.append(c.get("text"))
                            # Handle thinking type blocks (nested structure)
                            elif c.get("type") == "thinking" and c.get("thinking"):
                                thinking_items = c.get("thinking")
                                if isinstance(thinking_items, list):
                                    for t in thinking_items:
                                        if isinstance(t, dict) and t.get("type") == "text" and t.get("text"):
                                            texts.append(t.get("text"))
                        response_text = "\n".join(t for t in texts if t)
                        print(f"[RESPONSE PARSING] Found {len(texts)} text block(s), response_text length: {len(response_text) if response_text else 0}")
                    elif isinstance(content, str):
                        response_text = content
                elif "results" in res and isinstance(res["results"], list) and res["results"]:
                    first = res["results"][0]
                    contents = first.get("content") or []
                    if isinstance(contents, list):
                        texts = [c.get("text") for c in contents if isinstance(c, dict) and c.get("text")]
                        response_text = "\n".join(t for t in texts if t)
            
            if not response_text:
                # If we got no text from parsing, include the full response for debugging
                print(f"[WARNING] No response text extracted from agent. Full response: {json.dumps(res, default=str)[:1000]}")
                response_text = json.dumps(res, default=str)[:500] or "No response generated"
            
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
            # For non-agent LLM
            response = llm.ask(message, context=ctx_table)
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
        error_str = str(e).lower()
        
        # Log the error
        print(f"[Chat Exception] {error_str}")
        
        # Check for token limit errors in exception message with expanded keywords
        token_keywords = ['token', 'length', 'too large', 'overflow', 'exceed', 'max_tokens', 'context_length', 'input_too_long', '413', '400']
        if any(keyword in error_str for keyword in token_keywords):
            try:
                all_context = get_transactions_from_db(session.get('username'))
                context = all_context  # In error case, assume full context was attempted
            except:
                context = []
            suggestion = _get_data_reduction_suggestions(all_context if 'all_context' in locals() else [], context)
            user_message = f'Too much data was sent to the AI. Please try again by {suggestion}'
            return jsonify({'error': str(e), 'response': user_message, 'is_token_error': True})
        
        return jsonify({'error': str(e), 'response': f'Error: {str(e)}'})


@chat_bp.route('/save_recommendation', methods=['POST'])
@login_required
def save_recommendation():
    """Save an AI insight/recommendation to the database"""
    from ..db import DB_URL
    from ..models import Recommendation, User
    
    try:
        data = request.json
        user_id = session.get('username')
        question = data.get('question', '')
        response = data.get('response', '')
        category = data.get('category', 'Other')
        
        if not question or not response:
            return jsonify({'success': False, 'error': 'Missing question or response'})
        
        # Import context manager
        from ..utils import get_db_session_context
        
        with get_db_session_context(DB_URL) as db_session:
            # Get user
            user = db_session.query(User).filter_by(username=user_id).first()
            if not user:
                return jsonify({'success': False, 'error': 'User not found'})
            
            # Create recommendation
            recommendation = Recommendation(
                user_id=user.id,
                question=question,
                response=response,
                category=category
            )
            db_session.add(recommendation)
            db_session.commit()
        
        return jsonify({'success': True, 'message': 'Recommendation saved'})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
