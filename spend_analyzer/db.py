from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

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