# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from database_manager import (
                create_agent_table_if_not_exists,
                create_tool_table_if_not_exists,
                create_tool_agent_mapping_table_if_not_exists,
                create_tags_table_if_not_exists,
                create_tag_tool_mapping_table_if_not_exists,
                create_tag_agentic_app_mapping_table_if_not_exists,
                create_models_table_if_not_exists,
                create_login_registration_table_if_not_exists,
                create_csrf_token_table_if_not_exists
            )


def initialize_tables():
    """Creates all the required tables in the database"""
    create_models_table_if_not_exists()
    create_agent_table_if_not_exists()
    create_tool_table_if_not_exists()
    create_tool_agent_mapping_table_if_not_exists()
    create_tags_table_if_not_exists()
    create_tag_tool_mapping_table_if_not_exists()
    create_tag_agentic_app_mapping_table_if_not_exists()
    create_login_registration_table_if_not_exists()
    create_csrf_token_table_if_not_exists()


if __name__ == "__main__":
    initialize_tables()
