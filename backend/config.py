import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "clio.db"
PDF_DIR = BASE_DIR / "data" / "papers" / "pdfs"

PDF_DIR.mkdir(parents=True, exist_ok=True)
