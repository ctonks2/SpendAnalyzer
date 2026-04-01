# Utility Scripts

This folder contains debugging and testing scripts for Spend Analyzer. These are **not part of the main application** and are used for development and maintenance tasks only.

## Available Scripts

### Database Utilities

- **check_db_path.py** - Verify the database file location and check if it exists
  ```bash
  python scripts/check_db_path.py
  ```

- **list_tables.py** - List all tables in the SQLite database
  ```bash
  python scripts/list_tables.py
  ```

- **reset_database.py** - **CAUTION**: Permanently delete all data from the database while keeping tables intact
  ```bash
  python scripts/reset_database.py
  ```

### Testing & Verification

- **test_date_parsing.py** - Test the date parsing functionality with various formats
  ```bash
  python scripts/test_date_parsing.py
  ```

- **verify_mistral.py** - Verify Mistral API key and basic connectivity
  ```bash
  python scripts/verify_mistral.py
  ```

- **verify_mistral_endpoints.py** - Test various Mistral API endpoints to find the correct one
  ```bash
  python scripts/verify_mistral_endpoints.py
  ```

## When to Use

These scripts are useful for:
- **Debugging** - When you need to verify database state
- **Testing** - When developing or testing new features
- **Maintenance** - When resetting test data during development
- **Integration Testing** - When verifying external API connections

## Important Notes

⚠️ **Be Careful!**
- `reset_database.py` will **permanently delete all data**
- Only run these scripts in development or testing environments
- Do not run these against production databases

## How to Run

All scripts should be run from the project root directory:
```bash
cd /path/to/Spend\ Analyzer
python scripts/check_db_path.py
```
