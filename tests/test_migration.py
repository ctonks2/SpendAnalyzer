"""
Migration tests - UPDATED for new SQLAlchemy schema

The schema was changed to:
- Location (store_name, store_number)
- Receipt (user_id, location_id, date, order_number, total_amount)
- LineItem (receipt_id, item_name, quantity, unit_price, total_price, etc.)
- User (username, password, theme)
- UserHistory (user_id, filename)
- Recommendation (user_id, question, response, category)
"""
import os
import sqlite3
from pathlib import Path
from spend_analyzer.data_manager import DataManager
from spend_analyzer.migrate import init_db
from spend_analyzer.db import reset_db, get_session
from spend_analyzer.models import User, Location, Receipt, LineItem


def test_init_db_creates_all_tables(tmp_path):
    """Test that init_db creates all required tables"""
    dbfile = tmp_path / "test_db.sqlite"
    db_url = f"sqlite:///{dbfile}"
    
    init_db(db_url)
    
    conn = sqlite3.connect(str(dbfile))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    conn.close()
    
    expected_tables = {
        'users', 'locations', 'receipts', 'line_items',
        'user_history', 'recommendations', 'reports'
    }
    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"


def test_receipt_has_user_id(tmp_path):
    """Test that receipts table has user_id foreign key"""
    dbfile = tmp_path / "test_db.sqlite"
    db_url = f"sqlite:///{dbfile}"
    
    init_db(db_url)
    
    conn = sqlite3.connect(str(dbfile))
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(receipts)")
    columns = {row[1] for row in cur.fetchall()}
    conn.close()
    
    assert 'user_id' in columns, "receipts table should have user_id column"
    assert 'location_id' in columns, "receipts table should have location_id column"