#!/usr/bin/env python3
"""View SQLite database contents."""
import sqlite3
import sys

DB_PATH = 'spend_data.db'

def format_row(row, col_widths):
    """Format a row with proper column widths."""
    return " | ".join(f"{str(val)[:width]:<{width}}" for val, width in zip(row, col_widths))

def view_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get all table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if not tables:
            print("No tables found in database.")
            return
        
        for (table_name,) in tables:
            print(f"\n{'='*80}")
            print(f"TABLE: {table_name}")
            print('='*80)
            
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            
            if rows:
                # Calculate column widths
                col_widths = [max(len(str(col)), max(len(str(row[i])) for row in rows)) for i, col in enumerate(columns)]
                
                # Print header
                print(format_row(columns, col_widths))
                print("-" * (sum(col_widths) + len(col_widths) * 3))
                
                # Print rows
                for row in rows:
                    print(format_row(row, col_widths))
                
                print(f"\nTotal rows: {len(rows)}")
            else:
                print("(empty table)")
        
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    view_db()
