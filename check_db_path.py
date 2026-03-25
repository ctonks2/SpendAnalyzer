#!/usr/bin/env python3
"""Check where the database is actually located"""
import os
import sys

# Add to path to import modules
sys.path.insert(0, os.getcwd())

from spend_analyzer.db import _PROJECT_ROOT, DB_URL

print("=" * 60)
print("DATABASE LOCATION CHECK")
print("=" * 60)
print(f"Current Working Directory: {os.getcwd()}")
print(f"_PROJECT_ROOT from db.py: {_PROJECT_ROOT}")
print(f"DB_URL: {DB_URL}")
print()
print("Expected (correct) location:")
print(f"  {os.path.join(os.getcwd(), 'spend_data.db')}")
print()
print("Actual location:")
extracted_path = DB_URL.replace('sqlite:///', '')
print(f"  {extracted_path}")
print()
if os.path.exists(extracted_path):
    print(f"✓ Database file EXISTS at: {extracted_path}")
    # Check if there's a spend_data.db at the root
    if os.path.exists('spend_data.db'):
        print(f"✓ Local spend_data.db ALSO EXISTS in current directory")
else:
    print(f"✗ Database file NOT FOUND at: {extracted_path}")
    if os.path.exists('spend_data.db'):
        print(f"✓ But spend_data.db EXISTS in current directory: {os.path.abspath('spend_data.db')}")
