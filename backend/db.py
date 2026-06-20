import sqlite3
import sqlite_vec
from sqlite_vec import serialize_float32
from pathlib import Path


def connect(path):
    db = sqlite3.connect(str(path))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def init_db(db_path):
    db = connect(db_path)
    cursor = db.cursor()

    # Create paper table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            abstract TEXT,
            source TEXT NOT NULL,
            authors TEXT,
            year INTEGER,
            doi TEXT,
            url TEXT,
            pdf_path TEXT,
            full_text TEXT,
            needs_review INTEGER DEFAULT 0,
            ingest_notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Add new columns if they don't exist (schema migration)
    cursor.execute("PRAGMA table_info(paper)")
    columns = {row[1] for row in cursor.fetchall()}

    if "pdf_path" not in columns:
        cursor.execute("ALTER TABLE paper ADD COLUMN pdf_path TEXT")
    if "full_text" not in columns:
        cursor.execute("ALTER TABLE paper ADD COLUMN full_text TEXT")
    if "needs_review" not in columns:
        cursor.execute("ALTER TABLE paper ADD COLUMN needs_review INTEGER DEFAULT 0")
    if "ingest_notes" not in columns:
        cursor.execute("ALTER TABLE paper ADD COLUMN ingest_notes TEXT")
    if "added_at" not in columns:
        cursor.execute("ALTER TABLE paper ADD COLUMN added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    # Create vec_bge_m3 virtual table (1024-dim, cosine distance)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_bge_m3
        USING vec0(paper_id integer primary key, embedding float[1024] distance_metric=cosine)
    """)

    # Create vec_specter2 virtual table (768-dim, L2 distance - default)
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_specter2
        USING vec0(paper_id integer primary key, embedding float[768])
    """)

    db.commit()
    db.close()


def has_embedding(db, paper_id, vec_table) -> bool:
    cursor = db.cursor()
    cursor.execute(f"SELECT 1 FROM {vec_table} WHERE paper_id = ?", (paper_id,))
    return cursor.fetchone() is not None


def insert_embedding(db, vec_table, paper_id, vector):
    vector_list = [float(x) for x in vector]
    cursor = db.cursor()
    cursor.execute(
        f"INSERT INTO {vec_table} (paper_id, embedding) VALUES (?, ?)",
        (paper_id, serialize_float32(vector_list)),
    )
    db.commit()
