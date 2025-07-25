import asyncio
from database_manager import (
                create_feedback_storage_table_if_not_exists,
                create_evaluation_logs_table,
                create_agent_evaluation_table,
                create_tool_evaluation_table
            )


async def initialize_tables():
    """Creates all the required tables in the database"""
    await create_feedback_storage_table_if_not_exists()
    await create_evaluation_logs_table()
    await create_agent_evaluation_table()
    await create_tool_evaluation_table()

if __name__ == "__main__":
    asyncio.run(initialize_tables())
