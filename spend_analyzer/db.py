from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()

# ====== DATABASE CONFIGURATION ======

# Get project root
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Determine database based on environment
if os.environ.get('FLASK_ENV') == 'production':
    # Use PostgreSQL in production
    DB_URL = os.environ.get('DATABASE_URL')
    if DB_URL and DB_URL.startswith('postgres://'):
        # Fix PostgreSQL URL scheme for SQLAlchemy 1.4+
        DB_URL = DB_URL.replace('postgres://', 'postgresql://', 1)
else:
    # Use SQLite in development with absolute path
    db_path = os.path.join(_PROJECT_ROOT, 'spend_data.db')
    DB_URL = f"sqlite:///{db_path}"


_engine = None
_Session = None


def reset_db():
    """Reset the database engine and session maker. Call this before reinitializing."""
    global _engine, _Session
    if _engine:
        _engine.dispose()
    _engine = None
    _Session = None


def get_engine(db_url):
    global _engine
    if _engine is None:
        _engine = create_engine(db_url, echo=False, future=True)
    return _engine


def get_session(db_url):
    global _Session
    if _Session is None:
        engine = get_engine(db_url)
        _Session = sessionmaker(bind=engine)
    return _Session()