# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from database_manager import (
                create_agent_table_if_not_exists,
                create_tool_table_if_not_exists,
                create_tool_agent_mapping_table_if_not_exists,
                create_tags_table_if_not_exists,
                create_tag_tool_mapping_table_if_not_exists,
                create_tag_agentic_app_mapping_table_if_not_exists,
                create_models_table_if_not_exists,
                create_feedback_storage_table_if_not_exists,
                create_login_credential_table_if_not_exists,
                create_evaluation_logs_table,
                create_agent_evaluation_table,
                create_tool_evaluation_table,
                create_recycle_tool_table_if_not_exists,
                create_recycle_agent_table_if_not_exists
            )


async def initialize_tables():
    """Creates all the required tables in the database"""
    await create_models_table_if_not_exists()
    await create_agent_table_if_not_exists()
    await create_tool_table_if_not_exists()
    await create_tool_agent_mapping_table_if_not_exists()
    await create_tags_table_if_not_exists()
    await create_tag_tool_mapping_table_if_not_exists()
    await create_tag_agentic_app_mapping_table_if_not_exists()
    await create_feedback_storage_table_if_not_exists()
    await create_login_credential_table_if_not_exists()
    await create_evaluation_logs_table()
    await create_agent_evaluation_table()
    await create_tool_evaluation_table()
    await create_recycle_tool_table_if_not_exists()
    await create_recycle_agent_table_if_not_exists()

if __name__ == "__main__":
    asyncio.run(initialize_tables())
