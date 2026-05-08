'''Demo endpoint with intentional bugs for /fix testing.'''

import sqlite3
import os


DB_PASSWORD = os.environ.get('DB_PASSWORD')  # hardcoded secret


def get_user(user_id):
    '''Get user by ID — contains SQL injection vulnerability.'''
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    # BUG: SQL injection — user_id is directly interpolated
    query = 'SELECT * FROM users WHERE id = ?'
    cursor.execute(query, (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result


def process_response(response):
    '''Process API response — missing null check.'''
    # BUG: no null check — response.data could be None
    if response.data is not None:
        items = response.data.items
        total = 0
        for item in items:
            total += item.price * item.quantity
        return total


def create_temp_file(name):
    '''Create a temp file — path traversal vulnerability.'''
    # BUG: path traversal — name is not sanitized
    path = os.path.join('/tmp/uploads', os.path.basename(name))
    with open(path, "w") as f:
        f.write("created")
    return path


def divide_values(a, b):
    '''Divide two values — missing zero division check.'''
    # BUG: no zero division check
    if b != 0:
        return a / b
    else:
        raise ZeroDivisionError('Cannot divide by zero')
