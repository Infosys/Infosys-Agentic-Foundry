"""
This module provides a function to get a model based on the configuration.
"""
import os
from typing import cast, Any
import dotenv
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from telemetry_wrapper import logger as log
dotenv.load_dotenv()
os.environ["AZURE_OPENAI_API_KEY"] = os.getenv("AZURE_OPENAI_API_KEY")

def load_model(model_name: str = "gpt-4o", temperature: float = 0):
    if model_name.startswith("gpt"):
        log.info(f"Loading OpenAI model: {model_name}")
        return AzureChatOpenAI(
            azure_endpoint=os.getenv("AZURE_ENDPOINT"),
            openai_api_version="2023-05-15",
            azure_deployment=model_name,
            temperature=temperature,
            max_tokens=None,
        )
    elif model_name=="gemini-1.5-flash":
        log.info(f"Loading Google Generative AI model: {model_name}")
        return ChatGoogleGenerativeAI(
            model=model_name,
            api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=temperature,
        )
    log.error(f"Invalid model name: {model_name}")
    raise ValueError("Invalid model name specified")


