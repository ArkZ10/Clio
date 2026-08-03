import os
from pathlib import Path

import dotenv

BASE_DIR = Path(__file__).parent.parent

# The backend previously never read .env (only scripts/ did), so env-driven
# settings had to come from the calling shell. Loading it here lets
# CLIO_VAULT_PATH resolve from the repo .env the same way scripts already work.
# override=False so a real shell env var still wins over the file.
dotenv.load_dotenv(BASE_DIR / ".env", override=False)

DB_PATH = BASE_DIR / "data" / "clio.db"
PDF_DIR = BASE_DIR / "data" / "papers" / "pdfs"
EXPLORE_CACHE_PATH = BASE_DIR / "data" / "explore_cache.json"

PDF_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("CLIO_HOST", "0.0.0.0")
PORT = int(os.environ.get("CLIO_PORT", "8000"))

# Absolute path to the Obsidian vault Clio reads (READ-ONLY). Never hardcoded --
# None when unset, which the vault routes surface as a clean 503 rather than a
# crash. Not coerced to Path here so "unset" and "set but missing" stay distinct.
VAULT_PATH = os.environ.get("CLIO_VAULT_PATH")
