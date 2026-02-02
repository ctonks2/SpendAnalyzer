import sys
from pathlib import Path

# Ensure project root is importable when running tests
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
