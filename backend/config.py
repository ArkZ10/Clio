import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "clio.db"
PDF_DIR = BASE_DIR / "data" / "papers" / "pdfs"
EXPLORE_CACHE_PATH = BASE_DIR / "data" / "explore_cache.json"

PDF_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("CLIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("CLIO_PORT", "8000"))
