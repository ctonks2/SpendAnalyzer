"""
API Blueprint Registry
Registers all API blueprints (v1, legacy) with the Flask app.

API Structure:
  /api/v1/           - Main versioned API endpoints
    - /receipts      - Receipt management
    - /items         - Line item management
    - /analytics     - Spending analytics
    - /chat          - AI chat and recommendations
  /api/legacy/       - Deprecated legacy endpoints (for backward compatibility)
    - /list_files    - List files in data/raw
    - /import_file   - Import single file
"""

from flask import Blueprint

# Import all blueprints
from .v1 import v1_bp
from .legacy import legacy_api_bp

# Create parent API blueprint
api_bp = Blueprint('api', __name__)

# Register all API blueprints
api_bp.register_blueprint(v1_bp)           # /api/v1/* endpoints
api_bp.register_blueprint(legacy_api_bp)   # /api/legacy/* endpoints

__all__ = ['api_bp']
