# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import sqlite3
import os

def create_database(db_name):
    """
    Create a new SQLite database.

    Parameters:
    db_name (str): The name of the database file to create.

    Returns:
    None
    """
    connection = sqlite3.connect(db_name)
    connection.close()

def create_connection(db_name):
    """
    Connect to an SQLite database and return the connection object.
    
    The function arguments:
        db_name: The name of the database file to connect to.
    
    The return value:
        A connection object to the SQLite database.
    """
    def dict_factory(cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    conn = None #initailizing the variables
    if os.path.exists(db_name):
        try:
            conn = sqlite3.connect(db_name)
            conn.row_factory = dict_factory
        except Exception as e:
            pass
        return conn
    else:
        raise ValueError('No such database exists')
        return None


def close_connection(conn):
    """
    Closes the database connection.

    Parameters:
    conn (sqlite3.Connection): The SQLite connection object to be closed.

    If the connection is not None, this function attempts to close it.
    If an exception occurs during the closing process, an error message is printed.

    Args:
    conn (sqlite3.Connection): The connection object to close.

    Returns:
    None
    """
    if conn is not None:
        try:
            conn.close()
        except Exception as e:
            pass
