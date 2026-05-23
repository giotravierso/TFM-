"""
pytest configuration for Smart-Claims Agent tests.

Sets DATA_DIR so tests can find ofac_mock.json and the XGBoost model
without needing to pass environment variables manually.
"""
import os
import sys
from pathlib import Path

# Ensure DATA_DIR points to the repo's data/ directory
_REPO_ROOT = Path(__file__).parent.parent
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))

# Add backend to sys.path so `from app.xxx import ...` works
sys.path.insert(0, str(_REPO_ROOT / "backend"))
