"""
API v1 Blueprint Registration
Registers all v1 API endpoints under /api/v1/ prefix
"""

from flask import Blueprint

# Import v1 blueprints
from .items import items_bp
from .receipts import receipts_bp

# Create parent blueprint for v1
v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# Register v1 sub-blueprints
v1_bp.register_blueprint(items_bp)
v1_bp.register_blueprint(receipts_bp)

__all__ = ['v1_bp']
