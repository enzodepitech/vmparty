import sqlite3
import os

DB_PATH = "storage/app.db"

def init_db():
    os.makedirs("storage", exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_name TEXT NOT NULL,
                vm_id INTEGER NOT NULL UNIQUE,
                vm_ip TEXT NOT NULL,
                student_emails TEXT NOT NULL
            )
        """)
        conn.commit()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
