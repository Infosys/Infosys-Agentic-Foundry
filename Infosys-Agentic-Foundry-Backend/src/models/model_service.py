# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
from typing import Any, Dict, List, Union, Tuple
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from src.models.azure_ai_model_service import AzureAIModelService
from src.database.repositories import ChatStateHistoryManagerRepository
from telemetry_wrapper import logger as log


class ModelService:
    """
    Service layer for managing LLM models.
    Handles database persistence, loading, and caching of LLM instances.
    """

    def __init__(self, chat_state_history_manager: ChatStateHistoryManagerRepository = None):
        """
        Initializes the ModelService.
        """
        self.chat_state_history_manager = chat_state_history_manager

        self._loaded_models: Dict[str, Union[AzureChatOpenAI, ChatOpenAI, ChatGoogleGenerativeAI]] = {} # Cache for loaded LLM instances

        self.azure_openai_models = self.convert_string_to_list(os.getenv("AZURE_OPENAI_MODELS", ""))
        self.azure_openai_gpt_5_models = self.convert_string_to_list(os.getenv("AZURE_OPENAI_GPT_5_MODELS", ""))
        self.google_genai_models = self.convert_string_to_list(os.getenv("GOOGLE_GENAI_MODELS", ""))
        self.gpt_oss_models = self.convert_string_to_list(os.getenv("GPT_OSS_MODELS", ""))

        self.azure_ai_model_service, self.azure_ai_model_service_gpt_5 = self.get_azure_ai_model_service()

        self.available_models = self.azure_openai_models + self.azure_openai_gpt_5_models + self.google_genai_models + self.gpt_oss_models
        self.available_models.sort()


    @staticmethod
    def convert_string_to_list(models_string: str) -> List[str]:
        """
        Converts a comma-separated string of model names into a list.

        Args:
            models_string (str): A comma-separated string of model names.

        Returns:
            List[str]: A list of model names.
        """
        return [model.strip() for model in models_string.split(",") if model.strip()]

    def get_azure_ai_model_service(self) -> Tuple[Union[AzureAIModelService, None], Union[AzureAIModelService, None]]:
        """
        Returns an instance of AzureAIModelService.
        """
        client_gpt, client_gpt_5 = None, None

        api_key = os.getenv("AZURE_OPENAI_API_KEY", None)
        api_base = os.getenv("AZURE_ENDPOINT", None)
        api_version = os.getenv("OPENAI_API_VERSION", None)

        if self.azure_openai_models and api_key and api_base and api_version:
            client_gpt = AzureAIModelService(
                api_key=api_key,
                api_base=api_base,
                api_version=api_version,
                model=self.azure_openai_models[0],
                chat_history_manager=self.chat_state_history_manager
            )

        api_key = os.getenv("AZURE_OPENAI_API_KEY_GPT_5", None)
        api_base = os.getenv("AZURE_ENDPOINT_GPT_5", None)
        api_version = os.getenv("OPENAI_API_VERSION_GPT_5", None)

        if self.azure_openai_gpt_5_models and api_key and api_base and api_version:
            client_gpt_5 = AzureAIModelService(
                api_key=api_key,
                api_base=api_base,
                api_version=api_version,
                model=self.azure_openai_gpt_5_models[0],
                chat_history_manager=self.chat_state_history_manager
            )
        return client_gpt, client_gpt_5

    async def _load_llm_instance(self, model_name: str, temperature: float = 0) -> AzureChatOpenAI | ChatOpenAI | ChatGoogleGenerativeAI:
        """
        Internal helper to load an LLM instance based on its name.
        (Logic moved from your original load_model function)
        """

        if model_name in self.azure_openai_models:
            api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
            if not api_key:
                log.error("AZURE_OPENAI_API_KEY environment variable is not set.")
                raise ValueError("AZURE_OPENAI_API_KEY is not set in environment variables.")

            log.info(f"Loading OpenAI model: {model_name}")
            return AzureChatOpenAI(
                openai_api_key=api_key,
                azure_endpoint=os.getenv("AZURE_ENDPOINT", ""),
                openai_api_version=os.getenv("OPENAI_API_VERSION", ""),
                azure_deployment=model_name,
                temperature=temperature,
                max_tokens=None,
            )

        if model_name in self.azure_openai_gpt_5_models:
            api_key = os.getenv("AZURE_OPENAI_API_KEY_GPT_5", "")
            if model_name != "gpt-5-chat":
                temperature = 1
            if not api_key:
                log.error("AZURE_OPENAI_API_KEY_GPT_5 environment variable is not set.")
                raise ValueError("AZURE_OPENAI_API_KEY_GPT_5 is not set in environment variables.")

            log.info(f"Loading OpenAI model: {model_name}")
            return AzureChatOpenAI(
                openai_api_key=api_key,
                azure_endpoint=os.getenv("AZURE_ENDPOINT_GPT_5", ""),
                openai_api_version=os.getenv("OPENAI_API_VERSION_GPT_5", ""),
                azure_deployment=model_name,
                temperature=temperature,
                max_tokens=None,
            )

        if model_name in self.google_genai_models:
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if not api_key:
                log.error("GOOGLE_API_KEY environment variable is not set.")
                raise ValueError("GOOGLE_API_KEY is not set in environment variables.")

            log.info(f"Loading Google Generative AI model: {model_name}")
            return ChatGoogleGenerativeAI(
                api_key=api_key,
                model=model_name,
                temperature=temperature,
            )

        if model_name in self.gpt_oss_models:
            api_key = "gpt-oss-api-key"
            base_url = os.getenv("GPT_OSS_BASE_URL_ENDPOINT", None)
            if not base_url:
                log.error("GPT_OSS_BASE_URL_ENDPOINT environment variable is not set.")
                raise ValueError("GPT_OSS_BASE_URL_ENDPOINT is not set in environment variables.")

            log.info(f"Loading GPT-OSS model: {model_name}")
            return ChatOpenAI(
                openai_api_key=api_key,
                openai_api_base=base_url,
                model=model_name,
                temperature=temperature,
            )

        log.error(f"Invalid model name: {model_name}")
        raise ValueError("Invalid model name specified")

    async def get_llm_model(self, model_name: str, temperature: float = 0) -> AzureChatOpenAI | ChatOpenAI | ChatGoogleGenerativeAI:
        """
        Retrieves a loaded LLM instance from the cache, or loads it if not present.

        Args:
            model_name (str): The name of the model to retrieve.
            temperature (float): The temperature setting for the LLM.

        Returns:
            Any: An instance of the loaded LLM.

        Raises:
            ValueError: If the model name is invalid or loading fails.
        """
        if temperature != 0:
            log.info(f"Model '{model_name}' with temperature {temperature} not in cache. Loading...")
            return await self._load_llm_instance(model_name, temperature)

        if model_name not in self._loaded_models:
            log.info(f"Model '{model_name}' not in cache. Loading and caching...")
            self._loaded_models[model_name] = await self._load_llm_instance(model_name, temperature)
        else:
            log.debug(f"Model '{model_name}' retrieved from cache.")
        return self._loaded_models[model_name]

    async def get_llm_model_using_python(self, model_name: str, temperature: float = 0) -> AzureAIModelService:
        """
        Creates and returns an LLM model instance using Python implementation.
        """

        if model_name in self.azure_openai_models:
            log.info(f"Creating llm model using python for model: {model_name}")
            return self.azure_ai_model_service.create_agent(model=model_name, temperature=temperature)

        if model_name in self.azure_openai_gpt_5_models:
            log.info(f"Creating llm model using python for model: {model_name}")
            return self.azure_ai_model_service_gpt_5.create_agent(model=model_name, temperature=temperature)

        log.error(f"Invalid model name: {model_name}")
        raise ValueError(f"Invalid model name: {model_name}")


    async def get_all_available_model_names(self) -> List[str]:
        """
        Retrieves a list of all available model names.

        Returns:
            List[str]: A list of available model names.
        """
        return self.available_models

    async def load_all_models_into_cache(self) -> Dict[str, Any]:
        """
        Retrieves all model names from the database and loads their LLM instances into the cache.
        This is useful for pre-warming the cache at application startup.

        Returns:
            Dict[str, Any]: A dictionary indicating the status of the caching operation,
                            including a list of successfully loaded and failed models.
        """
        log.info("Starting to load all models from database into cache.")
        
        all_model_names = self.available_models
        
        loaded_count = 0
        failed_models = []

        for model_name in all_model_names:
            if model_name in self._loaded_models:
                log.debug(f"Model '{model_name}' already in cache. Skipping.")
                loaded_count += 1
                continue
            
            try:
                self._loaded_models[model_name] = await self._load_llm_instance(model_name)
                log.info(f"Model '{model_name}' loaded and cached successfully.")
                loaded_count += 1
            except Exception as e:
                log.error(f"Failed to load model '{model_name}' into cache: {e}")
                failed_models.append(model_name)
                
        log.info(f"Finished loading models into cache. Loaded: {loaded_count}, Failed: {len(failed_models)}.")
        
        return {
            "status": "completed",
            "loaded_count": loaded_count,
            "failed_models": failed_models,
            "message": f"Loaded {loaded_count} models into cache. {len(failed_models)} models failed to load."
        }


