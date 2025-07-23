import asyncio
from database_manager import create_feedback_storage_table_if_not_exists
async def initialize_tables():
    """Creates all the required tables in the database"""
   
    await create_feedback_storage_table_if_not_exists()
if __name__ == "__main__":
    asyncio.run(initialize_tables())