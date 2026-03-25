from spend_analyzer.data_manager import DataManager

# Test date parsing
dm = DataManager()

# Test with a sample row that mimics the Smiths JSON structure
test_rows = [
    {"date": "08/23/2023 00:00:00", "item": "test item", "store": "131", "price": "5.00"},
    {"date": "05/21/2023 00:00:00", "item": "another item", "store": "030", "price": "10.00"},
    {"date": "2026-03-25", "item": "iso format", "store": "131", "price": "3.00"},
]

print("Testing date parsing:")
for row in test_rows:
    tx = dm._normalize_row(row, "test_user")
    print(f"  Input: {row['date']:<30} -> Output: {tx.get('date')}")
