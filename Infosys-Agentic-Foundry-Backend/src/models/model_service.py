# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
from typing import Any, Dict, List, Union, Tuple
from langchain_openai import ChatOpenAI  # Direct OpenAI (Azure uses AzureChatOpenAI from langchain_openai)
from langchain_openai import AzureChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from google.adk.models.lite_llm import LiteLlm

from src.models.azure_ai_model_service import AzureAIModelService
from src.models.guardrail_aware_llm import (
    GuardrailAzureChatOpenAI,
    GuardrailChatOpenAI,
    GuardrailError,
    TokenLoggingAzureChatOpenAI,
    TokenLoggingChatAnthropic
)
from src.database.repositories import ChatStateHistoryManagerRepository
from src.config.constants import ModelNames
from telemetry_wrapper import logger as log
from src.utils.guardrail_helpers import guardrail_type_ctx as _guardrail_type_ctx
from src.utils.secrets_handler import current_request_headers


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

        self._loaded_models: Dict[str, Union[AzureChatOpenAI, ChatOpenAI, ChatGoogleGenerativeAI, ChatAnthropic]] = {} # Cache for loaded LLM instances

        # Gateway auth configuration (forward Authorization header to LLM calls)
        self._gateway_auth_enabled = os.getenv("LLM_FORWARD_AUTH_TOKEN", "false").lower() == "true"

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

        # Claude (Anthropic via Azure AI Foundry) configuration
        self.__claude_api_key = os.getenv("CLAUDE_API_KEY", None)
        self.__claude_endpoint = os.getenv("CLAUDE_ENDPOINT", None)
        self.__claude_deployment_name = os.getenv("CLAUDE_DEPLOYMENT_NAME", None)
        self.claude_models = []
        if self.__claude_api_key and self.__claude_endpoint:
            self.claude_models = self.convert_string_to_list(os.getenv("CLAUDE_MODELS", ""))

        # Claude (direct Anthropic API — no Azure, just sk-ant-... key) configuration
        self.__anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", None)
        self.anthropic_direct_models = []
        if self.__anthropic_api_key:
            self.anthropic_direct_models = self.convert_string_to_list(os.getenv("ANTHROPIC_MODELS", ""))

        # Additional Azure OpenAI endpoints (JSON-based config for scaling beyond 2 endpoints)
        self._additional_azure_endpoints: List[Dict[str, str]] = []
        self.additional_azure_models: List[str] = []
        self._model_to_additional_azure_config: Dict[str, Dict[str, str]] = {}
        additional_endpoints_json = os.getenv("AZURE_OPENAI_ADDITIONAL_ENDPOINTS", "")
        if additional_endpoints_json:
            try:
                self._additional_azure_endpoints = json.loads(additional_endpoints_json)
                for endpoint_config in self._additional_azure_endpoints:
                    api_key = endpoint_config.get("api_key", "")
                    endpoint = endpoint_config.get("endpoint", "")
                    api_version = endpoint_config.get("api_version", "")
                    gateway_mode = str(endpoint_config.get("gateway_mode", "false")).lower() == "true"
                    models_str = endpoint_config.get("models", "")

                    # In gateway_mode, if models not specified, extract from URL's last path segment
                    if gateway_mode and not models_str.strip():
                        # e.g. https://gateway.com/path/deployments/isgpt52/ → "isgpt52"
                        stripped_url = endpoint.rstrip("/")
                        models_str = stripped_url.split("/")[-1]
                        log.info(f"Gateway mode: extracted model name '{models_str}' from endpoint URL")

                    models = self.convert_string_to_list(models_str)
                    if api_key and endpoint and models:
                        for model in models:
                            self._model_to_additional_azure_config[model] = {
                                "api_key": api_key,
                                "endpoint": endpoint,
                                "api_version": api_version,
                                "gateway_mode": gateway_mode,
                            }
                self.additional_azure_models = list(self._model_to_additional_azure_config.keys())
                if self.additional_azure_models:
                    log.info(f"Loaded {len(self.additional_azure_models)} additional Azure OpenAI models from {len(self._additional_azure_endpoints)} endpoint(s).")
            except json.JSONDecodeError as e:
                log.error(f"Failed to parse AZURE_OPENAI_ADDITIONAL_ENDPOINTS JSON: {e}")

        self.azure_ai_model_service, self.azure_ai_model_service_gpt_5 = self.get_azure_ai_model_service()

        # Get all available models
        default_model_name = os.getenv("DEFAULT_MODEL_NAME", ModelNames.GPT_4O.value)
        self.available_models = self.litellm_models + self.azure_openai_models + self.azure_openai_gpt_5_models + self.additional_azure_models + self.google_genai_models + self.gpt_oss_models + self.openai_models + self.claude_models + self.anthropic_direct_models
        self.available_models = list(set(self.available_models))
        # self.available_models.sort()
        if default_model_name in self.available_models:
            self.available_models.remove(default_model_name)
            self.available_models.insert(0, default_model_name)
        
        # Mark that tracker hooks need to be registered (will be done when event loop is available)
        # ModelService.__init__ runs at module import time before any event loop is active,
        # so asyncio.create_task() would raise RuntimeError if we called register_tracker_hooks() here.
        # Instead, _ensure_tracker_hooks_registered() will be called lazily from async methods.
        self._tracker_hooks_registered = False
        
        if self.use_litellm_proxy:
            log.info(f"LiteLLM Proxy enabled. Endpoint: {self.litellm_endpoint}")
            if not self.litellm_models:
                log.warning(
                    "USE_LITELLM_PROXY_FLAG is enabled but LITELLM_MODELS is empty. "
                    "No models will be routed through the LiteLLM proxy. "
                    "Set LITELLM_MODELS in .env to route models through the LiteLLM proxy."
                )


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

    async def _ensure_tracker_hooks_registered(self):
        """
        Ensure tracker hooks are registered (only once, when event loop is available).
        """
        if not self._tracker_hooks_registered:
            try:
                from litellm_standalone_tracker import register_tracker_hooks
                await register_tracker_hooks()
                self._tracker_hooks_registered = True
                log.info("✅ Tracker hooks registered successfully")
            except Exception as e:
                log.error(f"Failed to register tracker hooks: {e}")

    def _get_gateway_auth_kwargs(self) -> dict:
        """Build model_kwargs with gateway Authorization header if enabled.
        
        Reads the LLM_FORWARD_AUTH_TOKEN env flag and, when true, extracts the
        Authorization token from the current request's ContextVar headers.
        Returns a dict suitable for passing as `model_kwargs` to LLM constructors.
        When disabled or no token is present, returns an empty dict.
        """
        if not self._gateway_auth_enabled:
            return {}
        headers = current_request_headers.get()
        auth_token = headers.get("authorization", "")
        if auth_token:
            log.debug(f"Gateway auth: injecting Authorization header into LLM call")
            return {"extra_headers": {"Authorization": auth_token}}
        return {}

    async def _load_llm_instance(self, model_name: str, temperature: float = 0) -> AzureChatOpenAI | ChatOpenAI | ChatGoogleGenerativeAI | ChatAnthropic:
        """Internal helper to load an LLM instance based on its name."""

        await self._ensure_tracker_hooks_registered()
        agent_guardrail_type = _guardrail_type_ctx.get(None)

        # Gateway auth: extra headers for proxied environments
        _gateway_kwargs = self._get_gateway_auth_kwargs()

        if agent_guardrail_type is not None:
            effective_guardrails = agent_guardrail_type != "none"
        else:
            try:
                from src.api.dependencies import ServiceProvider
                admin_config_service = ServiceProvider.get_admin_config_service()
                admin_config = await admin_config_service.get_limits()
                admin_guardrail_type = admin_config.guardrail_type
                effective_guardrails = admin_guardrail_type and admin_guardrail_type != "none"
                if effective_guardrails:
                    _guardrail_type_ctx.set(admin_guardrail_type)
            except Exception:
                effective_guardrails = False

        # Check if using LiteLLM proxy with guardrails
        if self.use_litellm_proxy and self.litellm_endpoint:
            api_key = self.litellm_api_key or "dummy-key"

            if model_name in self.litellm_models:
                if "gpt-5" in model_name:
                    temperature = 1

                if effective_guardrails:
                    log.info(f"Loading model via LiteLLM proxy with guardrails: {model_name}")
                    return GuardrailAzureChatOpenAI(
                        openai_api_key=api_key,
                        azure_endpoint=self.litellm_endpoint,
                        openai_api_version=self.litellm_api_version or "",
                        azure_deployment=model_name,
                        temperature=temperature,
                        max_tokens=None,
                        model_kwargs=_gateway_kwargs,
                    )
                else:
                    log.info(f"Loading model via LiteLLM proxy without guardrails: {model_name}")
                    return TokenLoggingAzureChatOpenAI(
                        openai_api_key=api_key,
                        azure_endpoint=self.litellm_endpoint,
                        openai_api_version=self.litellm_api_version or "",
                        azure_deployment=model_name,
                        temperature=temperature,
                        max_tokens=None,
                        model_kwargs=_gateway_kwargs,
                    )

            if model_name in self.openai_models + self.google_genai_models + self.gpt_oss_models:
                if effective_guardrails:
                    log.info(f"Loading model via LiteLLM proxy with guardrails (RAI + PII): {model_name}")
                else:
                    log.info(f"Loading model via LiteLLM proxy without guardrails (with token logging): {model_name}")
                # Use GuardrailChatOpenAI in both cases — GuardrailMixin is a no-op
                # when the proxy has no guardrails, but TokenLoggingMixin ensures
                # LLM request tracing and token tracking always fire.
                return GuardrailChatOpenAI(
                    openai_api_key=api_key,
                    openai_api_base=self.litellm_endpoint,
                    model=model_name,
                    temperature=temperature,
                    max_retries=10,
                    model_kwargs=_gateway_kwargs,
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
                model_kwargs=_gateway_kwargs,
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
                model_kwargs=_gateway_kwargs,
            )

        # Additional Azure OpenAI endpoints (JSON-based)
        if model_name in self.additional_azure_models:
            config = self._model_to_additional_azure_config[model_name]
            if config.get("gateway_mode"):
                # Gateway mode: endpoint URL already includes deployment path,
                # use openai_api_base so SDK appends only /chat/completions
                log.info(f"Loading additional Azure OpenAI model (gateway mode) with token logging: {model_name}")
                return TokenLoggingAzureChatOpenAI(
                    openai_api_key=config["api_key"],
                    openai_api_base=config["endpoint"],
                    openai_api_version=config["api_version"],
                    azure_deployment=None,
                    model_name=None,
                    validate_base_url=False,
                    temperature=temperature,
                    max_retries=10,
                    max_tokens=None,
                    default_headers=_gateway_kwargs.get("extra_headers", {}),
                )
            else:
                log.info(f"Loading additional Azure OpenAI model with token logging: {model_name}")
                return TokenLoggingAzureChatOpenAI(
                    openai_api_key=config["api_key"],
                    azure_endpoint=config["endpoint"],
                    openai_api_version=config["api_version"],
                    azure_deployment=model_name,
                    temperature=temperature,
                    max_retries=10,
                    max_tokens=None,
                    model_kwargs=_gateway_kwargs,
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
                max_retries=10,
                model_kwargs=_gateway_kwargs,
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
                max_retries=10,
                extra_headers=_gateway_kwargs.get("extra_headers", {}),
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
                max_retries=10,
                model_kwargs=_gateway_kwargs,
            )

        if model_name in self.claude_models:
            if not self.__claude_api_key or not self.__claude_endpoint:
                log.error("Claude (Anthropic) environment variables are not set.")
                raise ValueError("CLAUDE_API_KEY and CLAUDE_ENDPOINT are not set in environment variables.")

            log.info(f"Loading Claude model via Azure Anthropic endpoint with token logging: {model_name}")
            return TokenLoggingChatAnthropic(
                api_key=self.__claude_api_key,
                base_url=self.__claude_endpoint,
                model=model_name,
                temperature=temperature,
                max_retries=10,
                extra_headers=_gateway_kwargs.get("extra_headers", {}),
            )

        if model_name in self.anthropic_direct_models:
            if not self.__anthropic_api_key:
                log.error("ANTHROPIC_API_KEY is not set.")
                raise ValueError("ANTHROPIC_API_KEY is not set in environment variables.")

            log.info(f"Loading Claude model via direct Anthropic API: {model_name}")
            return TokenLoggingChatAnthropic(
                api_key=self.__anthropic_api_key,
                model=model_name,
                temperature=temperature,
                max_retries=10,
                extra_headers=_gateway_kwargs.get("extra_headers", {}),
            )

    async def get_llm_model(self, model_name: str, temperature: float = 0) -> AzureChatOpenAI | ChatOpenAI | ChatGoogleGenerativeAI | ChatAnthropic:
        """
        Retrieves a loaded LLM instance from the cache, or loads it if not present.

        Args:
            model_name (str): The name of the model to retrieve.
            temperature (float): The temperature setting for the LLM.
        """
        if _guardrail_type_ctx.get(None) is not None or temperature != 0 or self._gateway_auth_enabled:
            return await self._load_llm_instance(model_name, temperature)

        try:
            from src.api.dependencies import ServiceProvider
            admin_config_service = ServiceProvider.get_admin_config_service()
            admin_config = await admin_config_service.get_limits()
            if admin_config.guardrail_type and admin_config.guardrail_type != "none":
                return await self._load_llm_instance(model_name, temperature)
        except Exception:
            pass

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
        
        # Ensure tracker hooks are registered (lazy initialization)
        await self._ensure_tracker_hooks_registered()

        # Gateway auth: extra headers for proxied environments
        _gateway_extra_headers = self._get_gateway_auth_kwargs().get("extra_headers", None)

        if model_name in self.azure_openai_models:
            log.info(f"Creating llm model using python for model: {model_name}")
            return self.azure_ai_model_service.create_agent(model=model_name, temperature=temperature, extra_headers=_gateway_extra_headers)

        if model_name in self.azure_openai_gpt_5_models:
            if model_name != ModelNames.GPT_5_CHAT.value:
                temperature = 1
            log.info(f"Creating llm model using python for model: {model_name}")
            return self.azure_ai_model_service_gpt_5.create_agent(model=model_name, temperature=temperature, extra_headers=_gateway_extra_headers)

        # Additional Azure OpenAI endpoints (JSON-based) - create AzureAIModelService on-the-fly
        if model_name in self.additional_azure_models:
            config = self._model_to_additional_azure_config[model_name]
            log.info(f"Creating llm model using python for additional Azure model: {model_name}")
            additional_service = AzureAIModelService(
                api_key=config["api_key"],
                api_base=config["endpoint"],
                api_version=config["api_version"],
                model=model_name,
                chat_history_manager=self.chat_state_history_manager,
                gateway_mode=config.get("gateway_mode", False)
            )
            return additional_service.create_agent(model=model_name, temperature=temperature, extra_headers=_gateway_extra_headers)

        log.error(f"Invalid model name: {model_name}")
        raise ValueError(f"Invalid model name: {model_name}")

    async def get_llm_model_using_google_adk(self, model_name: str, temperature: float = 0) -> LiteLlm:
        """
        Creates and returns an LiteLLM model instance using Google ADK.
        
        Note: Tracker hooks are NOT registered for Google ADK to avoid streaming errors.
        Google ADK's LiteLLM wrapper has compatibility issues with standard LiteLLM callbacks.
        """
        
        # DO NOT register tracker hooks for Google ADK - causes streaming errors
        log.info("Using Google ADK LiteLLM wrapper (tracker hooks disabled for compatibility)")
        
        # Gateway auth: extra headers for proxied environments
        _gateway_extra_headers = self._get_gateway_auth_kwargs().get("extra_headers", {})

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
                    temperature=0,
                    extra_headers=_gateway_extra_headers or None,
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
                extra_headers=_gateway_extra_headers or None,
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
                extra_headers=_gateway_extra_headers or None,
            )

        # Additional Azure OpenAI endpoints (JSON-based)
        if model_name in self.additional_azure_models:
            config = self._model_to_additional_azure_config[model_name]
            if config.get("gateway_mode"):
                # Gateway mode: append /openai/deployments/../../ to the endpoint URL so that
                # litellm's azure handler recognizes it as base_url (bypasses /openai/ insertion)
                # and httpx normalizes the path traversal back to the original endpoint.
                _gw_endpoint = config["endpoint"].rstrip("/") + "/openai/deployments/../../"
                _gw_headers = dict(_gateway_extra_headers) if _gateway_extra_headers else {}
                _gw_headers["Authorization"] = _gw_headers.get("Authorization", "")
                log.info(f"Loading additional Azure OpenAI model (gateway mode) using Google ADK: {model_name}")
                return LiteLlm(
                    model=f"azure/",
                    api_key=config["api_key"],
                    api_base=_gw_endpoint,
                    api_version=config["api_version"],
                    temperature=temperature,
                    extra_headers=_gw_headers or None,
                )
            else:
                log.info(f"Loading additional Azure OpenAI model using Google ADK: {model_name}")
                return LiteLlm(
                    model=f"azure/{model_name}",
                    api_key=config["api_key"],
                    api_base=config["endpoint"],
                    api_version=config["api_version"],
                    temperature=temperature,
                    extra_headers=_gateway_extra_headers or None,
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
                extra_headers=_gateway_extra_headers or None,
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
                extra_headers=_gateway_extra_headers or None,
            )

        if model_name in self.claude_models:
            if not self.__claude_api_key or not self.__claude_endpoint:
                log.error("Claude (Anthropic) environment variables are not set.")
                raise ValueError("CLAUDE_API_KEY and CLAUDE_ENDPOINT are not set in environment variables.")

            log.info(f"Loading Claude model using Google ADK via Azure Anthropic: {model_name}")
            return LiteLlm(
                model=f"anthropic/{model_name}",
                api_key=self.__claude_api_key,
                api_base=self.__claude_endpoint,
                temperature=temperature,
                extra_headers=_gateway_extra_headers or None,
            )

        if model_name in self.anthropic_direct_models:
            if not self.__anthropic_api_key:
                log.error("ANTHROPIC_API_KEY is not set.")
                raise ValueError("ANTHROPIC_API_KEY is not set in environment variables.")

            log.info(f"Loading Claude model using Google ADK via direct Anthropic API: {model_name}")
            return LiteLlm(
                model=f"anthropic/{model_name}",
                api_key=self.__anthropic_api_key,
                temperature=temperature,
                extra_headers=_gateway_extra_headers or None,
            )

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

