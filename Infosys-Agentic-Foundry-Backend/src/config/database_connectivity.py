# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncpg
import os
from telemetry_wrapper import logger as log

async def create_database(db_name: str):
    """
    Create a new PostgreSQL database using a connection string.

    Parameters:
    db_name (str): The name of the database to create.

    Returns:
    None
    """
    dsn = os.getenv("POSTGRESQL_DATABASE_URL", "")

    conn = await asyncpg.connect(dsn)

    try:
        await conn.execute(f'CREATE DATABASE "{db_name}";')
    except asyncpg.DuplicateDatabaseError:
        log.error(f"Database '{db_name}' already exists.")
    except asyncpg.PostgresError as e:
        log.error(f"Error creating database: {e}")
    finally:
        await conn.close()

async def create_connection(dsn):
    """
    Connect to a PostgreSQL database using asyncpg and a DSN string.

    Arguments:
        dsn: A PostgreSQL DSN string like 'postgresql://user:<PWD>@host:port/database'

    Returns:
        An asyncpg connection object.
    """
    try:
        conn = await asyncpg.connect(dsn)
        return conn
    except asyncpg.PostgresError as e:
        log.error(f"PostgreSQL error occurred: {e}")
        return None


async def close_connection(conn):
    """
    Closes the asyncpg database connection.

    Parameters:
    conn (asyncpg.Connection): The PostgreSQL connection object to be closed.

    If the connection is not None, this function attempts to close it asynchronously.
    If an exception occurs during the closing process, an error message is printed.

    Returns:
    None
    """
    if conn is not None:
        try:
            await conn.close()
        except Exception as e:
            log.error(f"Unable to close the connection: {e}")
