import logging
import sqlite3
import os

from app.core.security import hash_password, verify_password
from app.core.utils import sanitize_email_to_username

DB_PATH = "storage/app.db"

def init_db():
    os.makedirs("storage", exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        create_vm_table(cursor)
        create_vm_user_table(cursor)
        conn.commit()

def create_vm_table(cursor):
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_name TEXT NOT NULL,
                vm_id INTEGER NOT NULL UNIQUE,
                vm_ip TEXT NOT NULL,
                student_emails TEXT NOT NULL
            )
        """)

def create_vm_user_table(cursor):
    """
    Table for user in linux vm
    """
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vm_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL
    )
    """)

def get_user(mail):
    conn = None
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM vm_users WHERE mail = ?", (mail,)).fetchone()
    conn.close()

    username = user["username"]
    hashed_password = user["password"]

    return mail, username, hashed_password

def get_vm(vm_id):
    conn = None
    conn = get_db_connection()
    vm_config = conn.execute("SELECT * FROM configs WHERE vm_id = ?", (vm_id,)).fetchone()
    conn.close()

    vm_ip = vm_config["vm_ip"]
    vm_name = vm_config["team_name"]
    student_emails = vm_config["student_emails"]

    return vm_id, vm_ip, vm_name, student_emails

def get_vm_byid(id):
    conn = None
    conn = get_db_connection()
    vm_config = conn.execute("SELECT * FROM configs WHERE id = ?", (id,)).fetchone()
    conn.close()

    vm_id = vm_config["vm_id"]
    vm_ip = vm_config["vm_ip"]
    vm_name = vm_config["team_name"]
    student_emails = vm_config["student_emails"]

    return vm_id, vm_ip, vm_name, student_emails

def create_vm(vm_name, vm_id, vm_ip, student_emails):
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO configs (team_name, vm_id, vm_ip, student_emails) VALUES (?, ?, ?, ?)",
            (vm_name, vm_id, vm_ip, student_emails)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        logging.error("VM ID must be unique.")
        raise ValueError("Cannot add VM: VM ID must be unique")
    finally:
        if conn:
            conn.close()

def create_user(mail, password):
    hashed_password = hash_password(password)
    username = sanitize_email_to_username(mail)
    
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO configs (mail, username, password) VALUES (?, ?, ?)",
            (mail, username, hashed_password)
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        logging.error(f"Cannot create user '{username}': {e}");
    finally:
        if conn:
            conn.close()

def delete_user(mail):
    username = sanitize_email_to_username(mail)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM configs WHERE mail = ?", (mail,))
        conn.commit()
        
        if cursor.rowcount == 0:
            logging.warning(f"No user found with email '{mail}' (username: {username}).")
            return False
            
        logging.info(f"User '{username}' ({mail}) deleted successfully.")
        return True

    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        logging.error(f"Error deleting user '{username}': {e}")
        return False
    finally:
        if conn:
            conn.close()
            
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
