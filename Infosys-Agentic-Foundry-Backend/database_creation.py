# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from database_manager import (
                create_models_table_if_not_exists,
                create_login_credential_table_if_not_exists,
                create_db_connections_table_if_not_exists
            )


async def initialize_tables():
    """Creates all the required tables in the database"""
    await create_models_table_if_not_exists()
    await create_login_credential_table_if_not_exists()
    await create_db_connections_table_if_not_exists()

if __name__ == "__main__":
    asyncio.run(initialize_tables())
