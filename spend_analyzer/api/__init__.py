"""
API Blueprint Registry
Registers all API blueprints (v1, legacy, analytics, chat) with the Flask app.
"""

from flask import Blueprint

# Import all blueprints
from .v1 import v1_bp
from .legacy import legacy_api_bp
from .analytics import analytics_bp
from .chat import chat_bp

# Create parent API blueprint
api_bp = Blueprint('api', __name__)

# Register all API sub-blueprints
api_bp.register_blueprint(v1_bp)
api_bp.register_blueprint(legacy_api_bp)
api_bp.register_blueprint(analytics_bp)
api_bp.register_blueprint(chat_bp)

__all__ = ['api_bp']
