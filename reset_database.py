#!/usr/bin/env python3
"""
One-time database reset script
Deletes all data from Spend Analyzer database while keeping tables intact
"""
import os
import sys

# Add to path to import modules
sys.path.insert(0, os.getcwd())

from spend_analyzer.db import get_session, DB_URL
from spend_analyzer.models import User, Receipt, LineItem, Location, Recommendation

def delete_all_data():
    """Delete all data from the database"""
    db_session = get_session(DB_URL)
    
    try:
        print("=" * 60)
        print("DATABASE RESET - DELETING ALL DATA")
        print("=" * 60)
        
        # Get counts before deletion
        user_count = db_session.query(User).count()
        receipt_count = db_session.query(Receipt).count()
        lineitem_count = db_session.query(LineItem).count()
        location_count = db_session.query(Location).count()
        recommendation_count = db_session.query(Recommendation).count()
        
        print(f"\nBefore deletion:")
        print(f"  Users: {user_count}")
        print(f"  Receipts: {receipt_count}")
        print(f"  Line Items: {lineitem_count}")
        print(f"  Locations: {location_count}")
        print(f"  Recommendations: {recommendation_count}")
        
        # Delete all data
        print("\nDeleting all data...")
        
        # Delete in order of dependencies
        db_session.query(Recommendation).delete()
        db_session.query(LineItem).delete()
        db_session.query(Receipt).delete()
        db_session.query(Location).delete()
        db_session.query(User).delete()
        
        db_session.commit()
        
        print("\n✓ All data deleted successfully!")
        print("\nAfter deletion:")
        print(f"  Users: 0")
        print(f"  Receipts: 0")
        print(f"  Line Items: 0")
        print(f"  Locations: 0")
        print(f"  Recommendations: 0")
        print("\n" + "=" * 60)
        
    except Exception as e:
        db_session.rollback()
        print(f"✗ Error deleting data: {str(e)}")
        return False
    finally:
        db_session.close()
    
    return True

if __name__ == '__main__':
    success = delete_all_data()
    sys.exit(0 if success else 1)
