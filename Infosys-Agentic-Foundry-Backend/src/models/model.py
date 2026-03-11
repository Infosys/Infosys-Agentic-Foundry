# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
This module provides a function to get a model based on the configuration.
"""
import dotenv
import asyncio
from src.models.model_service import global_model_service
from telemetry_wrapper import logger as log

dotenv.load_dotenv()

def load_model(model_name: str = global_model_service.default_model_name, temperature: float = 0):
    """
    Load and return a llm model instance of langgraph based on the provided model name and temperature.
    """
    get_model_async_call = global_model_service.get_llm_model(model_name=model_name, temperature=temperature)
    log.info(f"Loading model: {model_name} with temperature: {temperature}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create one
        log.debug("No running event loop found, creating new event loop with asyncio.run()")
        return asyncio.run(get_model_async_call)
    else:
        # There's a running loop - use run_until_complete or nest_asyncio
        log.debug("Running event loop detected, using nest_asyncio for nested async execution")
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(get_model_async_call)


