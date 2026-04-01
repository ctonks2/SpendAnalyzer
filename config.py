"""
Production and development configuration for Spend Analyzer

All sensitive configuration is loaded from environment variables via python-dotenv.
No hardcoded secrets or sensitive data should be present in this file.
"""

import os
from datetime import timedelta

class Config:
    """Base configuration"""
    # Security - SECRET_KEY is required and must come from environment
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        if os.environ.get('FLASK_ENV') == 'production':
            raise ValueError(
                "CRITICAL: SECRET_KEY is not set. "
                "In production, SECRET_KEY must be set via environment variable. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        # In development, provide a warning but allow continuation
        print("⚠️  WARNING: SECRET_KEY not set. Using temporary key for development only!")
        SECRET_KEY = "dev-temporary-key-do-not-use-in-production"
    
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # Database
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Max file upload size (5MB)
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024))
    
    # Flask settings
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = False


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False
    SQLALCHEMY_ECHO = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    """Production configuration
    
    In production, the following environment variables are REQUIRED:
    - SECRET_KEY: Flask session signing key
    - DATABASE_URL: PostgreSQL database URL
    """
    DEBUG = False
    TESTING = False
    # Enforce HTTPS in production
    SESSION_COOKIE_SECURE = True
    
    def __init__(self):
        """Validate production environment variables when config is instantiated"""
        super().__init__()
        DATABASE_URL = os.environ.get('DATABASE_URL')
        if not DATABASE_URL:
            raise ValueError(
                "CRITICAL: DATABASE_URL is not set. "
                "In production, DATABASE_URL must be set via environment variable. "
                "Example: postgresql://user:password@host:5432/spend_analyzer"
            )


class TestingConfig(Config):
    """Testing configuration"""
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SESSION_COOKIE_SECURE = False
