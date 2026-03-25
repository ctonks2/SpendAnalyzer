"""
Chat/LLM API Blueprint
Provides AI chat and recommendation endpoints.
"""

from flask import Blueprint, jsonify, session, request
from functools import wraps
import json

chat_bp = Blueprint('api_chat', __name__, url_prefix='/api')


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function


@chat_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    """
    API endpoint for LLM chat with spending data context.
    Accepts chat message and optional conversation history.
    """
    from spend_analyzer.db import (
        get_transactions_from_db, filter_context_by_question,
        context_to_table
    )
    from spend_analyzer.llm_client import LLMClient
    
    try:
        data = request.json
        user_id = session.get('username')
        message = data.get('message')
        history = data.get('history', [])  # List of {question, response} dicts
        
        if not message:
            return jsonify({'error': 'Missing message'})
        
        # Load user data and filter by question
        all_context = get_transactions_from_db(user_id)
        context, filters_applied = filter_context_by_question(all_context, message)
        
        # Use compact table format
        ctx_table = context_to_table(context)
        
        # Build conversation history string
        history_str = ""
        if history:
            recent_history = history[-3:]
            history_parts = []
            for h in recent_history:
                if h.get('question') and h.get('response'):
                    history_parts.append(f"User: {h['question']}\nAssistant: {h['response']}")
            if history_parts:
                history_str = "\n\nPrevious conversation:\n" + "\n\n".join(history_parts)
        
        # Get LLM instance
        llm = LLMClient()
        
        # Check if using agent
        if getattr(llm, 'agent_id', None):
            filter_info = f"(Filtered {len(context)} of {len(all_context)} transactions: {', '.join(filters_applied)})"
            full_content = f"Transaction Data {filter_info}:\n{ctx_table}{history_str}\n\nCurrent question:\n{message}"
            
            res = llm.start_agent_conversation(inputs=[{"role": "user", "content": full_content}])
            
            if isinstance(res, dict) and res.get("error"):
                error_detail = res.get('body', res.get('error'))
                return jsonify({'error': str(error_detail), 'response': f'Sorry, I encountered an error.'})
            
            # Parse agent response
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
            # For non-agent LLM
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
