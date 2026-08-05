import os
from pathlib import Path

import dotenv

BASE_DIR = Path(__file__).parent.parent

# override=False so a real shell env var still wins over the file.
dotenv.load_dotenv(BASE_DIR / ".env", override=False)

DB_PATH = BASE_DIR / "data" / "clio.db"
PDF_DIR = BASE_DIR / "data" / "papers" / "pdfs"
EXPLORE_CACHE_PATH = BASE_DIR / "data" / "explore_cache.json"

PDF_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("CLIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("CLIO_PORT", "8000"))

# The Obsidian vault Clio reads (read-only). None when unset -- the vault
# routes turn that into a clean 503 rather than a crash.
VAULT_PATH = os.environ.get("CLIO_VAULT_PATH")
