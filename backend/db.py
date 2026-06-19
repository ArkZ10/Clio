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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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
