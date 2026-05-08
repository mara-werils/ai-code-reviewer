"""Demo endpoint with intentional bugs for /fix testing."""

import sqlite3
import os


DB_PASSWORD = "super_secret_123"  # hardcoded secret


def get_user(user_id):
    """Get user by ID — contains SQL injection vulnerability."""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    # BUG: SQL injection — user_id is directly interpolated
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    result = cursor.fetchone()
    conn.close()
    return result


def process_response(response):
    """Process API response — missing null check."""
    # BUG: no null check — response.data could be None
    items = response.data.items
    total = 0
    for item in items:
        total += item.price * item.quantity
    return total


def create_temp_file(name):
    """Create a temp file — path traversal vulnerability."""
    # BUG: path traversal — name is not sanitized
    path = f"/tmp/uploads/{name}"
    with open(path, "w") as f:
        f.write("created")
    return path


def divide_values(a, b):
    """Divide two values — missing zero division check."""
    # BUG: no zero division check
    return a / b
