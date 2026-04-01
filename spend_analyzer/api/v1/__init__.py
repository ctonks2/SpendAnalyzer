"""
API v1 Blueprint Registration
Registers all v1 API endpoints under /api/v1/ prefix

Includes:
  /api/v1/receipts    - Receipt management (CRUD operations)
  /api/v1/items       - Line item management
  /api/v1/analytics   - Spending analytics and insights
  /api/v1/chat        - AI chat and recommendations
"""

from flask import Blueprint

# Create parent blueprint for v1
v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# Import and register v1 blueprints
from .items import items_bp
from .receipts import receipts_bp
from ..analytics import analytics_bp
from ..chat import chat_bp

# Register all v1 sub-blueprints
v1_bp.register_blueprint(items_bp)
v1_bp.register_blueprint(receipts_bp)
v1_bp.register_blueprint(analytics_bp)
v1_bp.register_blueprint(chat_bp)

__all__ = ['v1_bp']
