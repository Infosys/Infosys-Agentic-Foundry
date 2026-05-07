# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
from typing import Any, Dict, List, Union, Tuple
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from google.adk.models.lite_llm import LiteLlm

from src.models.azure_ai_model_service import AzureAIModelService
from src.models.guardrail_aware_llm import (
    GuardrailAzureChatOpenAI,
    GuardrailChatOpenAI,
    GuardrailError,
    TokenLoggingAzureChatOpenAI
)
from src.database.repositories import ChatStateHistoryManagerRepository
from src.config.constants import ModelNames
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

        # LiteLLM Proxy configuration (for guardrails and token tracking)
        self.use_litellm_proxy = os.getenv("USE_LITELLM_PROXY_FLAG", "false").lower() == "true"
        self.litellm_endpoint = os.getenv("LITELLM_ENDPOINT", None)
        self.litellm_api_key = os.getenv("LITELLM_API_KEY", None)
        self.litellm_api_version = os.getenv("LITELLM_API_VERSION", None)
        self.litellm_models = []
        if self.use_litellm_proxy and self.litellm_endpoint and self.litellm_api_key:
            self.litellm_models = self.convert_string_to_list(os.getenv("LITELLM_MODELS", ""))

        # Azure OpenAI configuration
        self.__azure_api_key = os.getenv("AZURE_OPENAI_API_KEY", None)
        self.__azure_api_base = os.getenv("AZURE_ENDPOINT", None)
        self.__azure_api_version = os.getenv("OPENAI_API_VERSION", None)
        self.azure_openai_models = []
        if self.__azure_api_key and self.__azure_api_base and self.__azure_api_version:
            self.azure_openai_models = self.convert_string_to_list(os.getenv("AZURE_OPENAI_MODELS", ""))

        # Azure OpenAI GPT-5 configuration
        self.__azure_gpt_5_api_key = os.getenv("AZURE_OPENAI_API_KEY_GPT_5", None)
        self.__azure_gpt_5_api_base = os.getenv("AZURE_ENDPOINT_GPT_5", None)
        self.__azure_gpt_5_api_version = os.getenv("OPENAI_API_VERSION_GPT_5", None)
        self.azure_openai_gpt_5_models = []
        if self.__azure_gpt_5_api_key and self.__azure_gpt_5_api_base and self.__azure_gpt_5_api_version:
            self.azure_openai_gpt_5_models = self.convert_string_to_list(os.getenv("AZURE_OPENAI_GPT_5_MODELS", ""))

        # Google Generative AI configuration
        self.__gemini_api_key = os.getenv("GOOGLE_API_KEY", "")
        self.google_genai_models = []
        if self.__gemini_api_key:
            self.google_genai_models = self.convert_string_to_list(os.getenv("GOOGLE_GENAI_MODELS", ""))

        # GPT-OSS configuration
        self.__gpt_oss_api_key = "gpt-oss-api-key"
        self.__gpt_oss_base_url = os.getenv("GPT_OSS_BASE_URL_ENDPOINT", None)
        self.gpt_oss_models = []
        if self.__gpt_oss_api_key and self.__gpt_oss_base_url:
            self.gpt_oss_models = self.convert_string_to_list(os.getenv("GPT_OSS_MODELS", ""))

        # OpenAI configuration
        self.__openai_api_key = os.getenv("OPENAI_API_KEY", None)
        self.__openai_base_url = os.getenv("OPENAI_BASE_URL_ENDPOINT", None)
        self.openai_models = []
        if self.__openai_api_key and self.__openai_base_url:
            self.openai_models = self.convert_string_to_list(os.getenv("OPENAI_MODELS", ""))


        self.azure_ai_model_service, self.azure_ai_model_service_gpt_5 = self.get_azure_ai_model_service()

        # Get all available models
        default_model_name = os.getenv("DEFAULT_MODEL_NAME", ModelNames.GPT_4O.value)
        self.available_models = self.litellm_models + self.azure_openai_models + self.azure_openai_gpt_5_models + self.google_genai_models + self.gpt_oss_models + self.openai_models
        self.available_models = list(set(self.available_models))
        # self.available_models.sort()
        if default_model_name in self.available_models:
            self.available_models.remove(default_model_name)
            self.available_models.insert(0, default_model_name)
        
        # Note: standalone tracker initialization (register_tracker_hooks) is intentionally
        # NOT called here. ModelService.__init__ runs at module import time before any
        # event loop is active, so asyncio.create_task() would raise RuntimeError.
        # register_tracker_hooks() is instead called from main.py lifespan() where the
        # event loop is guaranteed to be running.
        
        if self.use_litellm_proxy:
            log.info(f"LiteLLM Proxy enabled - using guardrail-aware wrappers. Endpoint: {self.litellm_endpoint}")


    @property
    def default_model_name(self) -> str:
        """
        Returns the default model name.
        """
        if not self.available_models:
            log.error("No models available. Please check your environment configuration.")
            raise ValueError("No models available. Ensure model environment variables are configured.")
        return self.available_models[0]

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
        
        # If using LiteLLM proxy, use unified configuration
        if os.getenv("USE_LITELLM_PROXY_FLAG", "false").lower() == "true":
            api_key = os.getenv("LITELLM_API_KEY", None)
            api_base = os.getenv("LITELLM_ENDPOINT", None)
            api_version = os.getenv("LITELLM_API_VERSION", None)
            
            if (self.azure_openai_models or self.azure_openai_gpt_5_models) and api_key and api_base and api_version:
                log.info(f"Initializing AzureAIModelService with LiteLLM endpoint: {api_base}")
                client_gpt = AzureAIModelService(
                    api_key=api_key,
                    api_base=api_base,
                    api_version=api_version,
                    model=(self.azure_openai_models + self.azure_openai_gpt_5_models)[0] if (self.azure_openai_models or self.azure_openai_gpt_5_models) else None,
                    chat_history_manager=self.chat_state_history_manager
                )
                client_gpt_5 = client_gpt
                return client_gpt, client_gpt_5

        # Standard Azure OpenAI configuration (when not using LiteLLM proxy)
        if self.azure_openai_models and self.__azure_api_key and self.__azure_api_base and self.__azure_api_version:
            client_gpt = AzureAIModelService(
                api_key=self.__azure_api_key,
                api_base=self.__azure_api_base,
                api_version=self.__azure_api_version,
                model=self.azure_openai_models[0],
                chat_history_manager=self.chat_state_history_manager
            )

        if self.azure_openai_gpt_5_models and self.__azure_gpt_5_api_key and self.__azure_gpt_5_api_base and self.__azure_gpt_5_api_version:
            client_gpt_5 = AzureAIModelService(
                api_key=self.__azure_gpt_5_api_key,
                api_base=self.__azure_gpt_5_api_base,
                api_version=self.__azure_gpt_5_api_version,
                model=self.azure_openai_gpt_5_models[0],
                chat_history_manager=self.chat_state_history_manager
            )
        return client_gpt, client_gpt_5

    async def _load_llm_instance(self, model_name: str, temperature: float = 0) -> AzureChatOpenAI | ChatOpenAI | ChatGoogleGenerativeAI:
        """
        Internal helper to load an LLM instance based on its name.
        Uses guardrail wrappers when LiteLLM proxy is enabled.
        """
        
        # Check if using LiteLLM proxy with guardrails
        if self.use_litellm_proxy and self.litellm_endpoint:
            if model_name in self.litellm_models:
                api_key = self.litellm_api_key or "dummy-key"
                if "gpt-5" in model_name:
                    temperature = 1
                
                log.info(f"Loading model via LiteLLM proxy with guardrails: {model_name}")
                return GuardrailAzureChatOpenAI(
                    openai_api_key=api_key,
                    azure_endpoint=self.litellm_endpoint,
                    openai_api_version=self.litellm_api_version or "",
                    azure_deployment=model_name,
                    temperature=temperature,
                    max_tokens=None,
                )

        # Original Azure OpenAI configuration
        if model_name in self.azure_openai_models:
            if not self.__azure_api_key or not self.__azure_api_base or not self.__azure_api_version:
                log.error("Azure model's environment variable is not set.")
                raise ValueError("Azure model's is not set in environment variables.")

            log.info(f"Loading Azure OpenAI model with token logging: {model_name}")
            return TokenLoggingAzureChatOpenAI(
                openai_api_key=self.__azure_api_key,
                azure_endpoint=self.__azure_api_base,
                openai_api_version=self.__azure_api_version,
                azure_deployment=model_name,
                temperature=temperature,
                max_retries=0,
                max_tokens=None,
            )

        if model_name in self.azure_openai_gpt_5_models:
            if model_name != ModelNames.GPT_5_CHAT.value:
                temperature = 1
            if not self.__azure_gpt_5_api_key or not self.__azure_gpt_5_api_base or not self.__azure_gpt_5_api_version:
                log.error("Azure GPT-5 model's environment variable is not set.")
                raise ValueError("Azure GPT-5 model's is not set in environment variables.")

            log.info(f"Loading Azure OpenAI GPT-5 model with token logging: {model_name}")
            return TokenLoggingAzureChatOpenAI(
                openai_api_key=self.__azure_gpt_5_api_key,
                azure_endpoint=self.__azure_gpt_5_api_base,
                openai_api_version=self.__azure_gpt_5_api_version,
                azure_deployment=model_name,
                temperature=temperature,
                max_retries=10,
                max_tokens=None,
            )
        
        if model_name in self.openai_models:
            api_key = self.__openai_api_key
            base_url = self.__openai_base_url
            if not base_url:
                log.error("OPENAI_BASE_URL_ENDPOINT environment variable is not set.")
                raise ValueError("OPENAI_BASE_URL_ENDPOINT is not set in environment variables.")

            log.info(f"Loading OpenAI model: {model_name}")
            return ChatOpenAI(
                openai_api_key=api_key,
                openai_api_base=base_url,
                model=model_name,
                temperature=temperature,
                max_retries=10
            )

        if model_name in self.google_genai_models:
            if not self.__gemini_api_key:
                log.error("Google Generative AI model's environment variable is not set.")
                raise ValueError("Google Generative AI model's is not set in environment variables.")

            log.info(f"Loading Google Generative AI model: {model_name}")
            return ChatGoogleGenerativeAI(
                api_key=self.__gemini_api_key,
                model=model_name,
                temperature=temperature,
                max_retries=10
            )

        if model_name in self.openai_models:
            if not self.__openai_api_key:
                log.error("OPENAI_API_KEY environment variable is not set.")
                raise ValueError("OPENAI_API_KEY is not set in environment variables.")

            log.info(f"Loading OpenAI model: {model_name}")
            return ChatOpenAI(
                api_key=self.__openai_api_key,
                base_url=self.__openai_base_url,
                model=model_name,
                temperature=temperature,
                max_retries=10
            )

        if model_name in self.gpt_oss_models:
            if not self.__gpt_oss_base_url:
                log.error("GPT_OSS_BASE_URL_ENDPOINT environment variable is not set.")
                raise ValueError("GPT_OSS_BASE_URL_ENDPOINT is not set in environment variables.")

            log.info(f"Loading GPT-OSS model: {model_name}")
            return ChatOpenAI(
                openai_api_key=self.__gpt_oss_api_key,
                openai_api_base=self.__gpt_oss_base_url,
                model=model_name,
                temperature=temperature,
                max_retries=10
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
            if model_name != ModelNames.GPT_5_CHAT.value:
                temperature = 1
            log.info(f"Creating llm model using python for model: {model_name}")
            return self.azure_ai_model_service_gpt_5.create_agent(model=model_name, temperature=temperature)

        log.error(f"Invalid model name: {model_name}")
        raise ValueError(f"Invalid model name: {model_name}")

    async def get_llm_model_using_google_adk(self, model_name: str, temperature: float = 0) -> LiteLlm:
        """
        Creates and returns an LiteLLM model instance using Google ADK.
        """
        # Check if using LiteLLM proxy with guardrails
        if self.use_litellm_proxy and self.litellm_endpoint:
            if model_name in self.litellm_models:
                api_key = self.litellm_api_key or "dummy-key"
                if "gpt-5" in model_name:
                    temperature = 1

                log.info(f"Loading model via LiteLLM proxy for Google ADK: {model_name}")
                return LiteLlm(
                    model=model_name,
                    api_key=api_key,
                    api_base=self.litellm_endpoint,
                    api_version=self.litellm_api_version or "",
                    temperature=0
                )
                    

        if model_name in self.azure_openai_models:
            if not self.__azure_api_key or not self.__azure_api_base or not self.__azure_api_version:
                log.error("Azure model's environment variable is not set.")
                raise ValueError("Azure model's is not set in environment variables.")

            log.info(f"Loading OpenAI model using Google ADK: {model_name}")
            return LiteLlm(
                model=f"azure/{model_name}",
                api_key=self.__azure_api_key,
                api_base=self.__azure_api_base,
                api_version=self.__azure_api_version,
                temperature=temperature,
            )

        if model_name in self.azure_openai_gpt_5_models:
            if model_name != ModelNames.GPT_5_CHAT.value:
                temperature = 1
            if not self.__azure_gpt_5_api_key or not self.__azure_gpt_5_api_base or not self.__azure_gpt_5_api_version:
                log.error("Azure GPT-5 model's environment variable is not set.")
                raise ValueError("Azure GPT-5 model's is not set in environment variables.")

            log.info(f"Loading OpenAI model using Google ADK: {model_name}")
            return LiteLlm(
                model=f"azure/{model_name}",
                api_key=self.__azure_gpt_5_api_key,
                api_base=self.__azure_gpt_5_api_base,
                api_version=self.__azure_gpt_5_api_version,
                temperature=1,
            )

        if model_name in self.openai_models:
            if not self.__openai_api_key:
                log.error("OPENAI_API_KEY environment variable is not set.")
                raise ValueError("OPENAI_API_KEY is not set in environment variables.")

            log.info(f"Loading OpenAI model using Google ADK: {model_name}")
            return LiteLlm(
                model=f"openai/{model_name}",
                api_key=self.__openai_api_key,
                api_base=self.__openai_base_url,
                temperature=temperature,
            )

        if model_name in self.gpt_oss_models:
            if not self.__gpt_oss_base_url:
                log.error("GPT_OSS_BASE_URL_ENDPOINT environment variable is not set.")
                raise ValueError("GPT_OSS_BASE_URL_ENDPOINT is not set in environment variables.")

            log.info(f"Loading GPT-OSS model using Google ADK: {model_name}")
            return LiteLlm(
                model=f"openai/{model_name}",
                api_key=self.__gpt_oss_api_key,
                api_base=self.__gpt_oss_base_url,
                temperature=temperature,
            )

        log.error(f"Invalid model name: {model_name}")
        raise ValueError("Invalid model name specified")

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


global_model_service = ModelService()

