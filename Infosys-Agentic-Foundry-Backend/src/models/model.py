# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
This module provides a function to get a model based on the configuration.
"""
import dotenv
import asyncio
import concurrent.futures
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
        asyncio.get_running_loop()
        # There's a running loop - run in a separate thread with its own event loop
        log.info("Running event loop detected, executing in separate thread")
        with concurrent.futures.ThreadPoolExecutor(1) as executor:
            return executor.submit(asyncio.run, get_model_async_call).result()
    except RuntimeError:
        # No running loop, safe to use asyncio.run directly
        log.info("No running event loop found, creating new event loop with asyncio.run()")
        return asyncio.run(get_model_async_call)


