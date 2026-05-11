"""
FastAPI Server with LiteLLM SDK

A standalone server that uses the LiteLLM Python SDK directly (no Prisma required).
Includes all features: RAI moderation, model routing/fallbacks, and database logging.

Usage:
    python server.py
    # or
    uvicorn server:app --host 0.0.0.0 --port 4000 --reload
"""

import os
import json
import yaml
import logging
import asyncio
import requests
import urllib3
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from contextlib import asynccontextmanager

import litellm
from litellm import acompletion, completion
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from moderation_db_service import get_moderation_db_service
from constants import LITELLM_LOGGING, env_bool

# Disable SSL warnings for proxy environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable litellm internal logging if configured
if not LITELLM_LOGGING:
    litellm.suppress_debug_info = True
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)

# Drop unsupported parameters for providers like Azure that don't support all OpenAI params
litellm.drop_params = True


# =============================================================================
# Pydantic Models for OpenAI-compatible API
# =============================================================================

class Message(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None  # Optional when using Azure-style deployment endpoint
    messages: List[Message]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0
    frequency_penalty: Optional[float] = 0
    user: Optional[str] = None
    # Moderation flags (None = use GUARDRAILS_PRE_CALL_ENABLED / GUARDRAILS_POST_CALL_ENABLED from .env)
    pre_call_moderation: Optional[bool] = None
    post_call_moderation: Optional[bool] = None


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: Optional[str] = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Optional[Usage] = None


# =============================================================================
# Configuration Loader
# =============================================================================

class ConfigLoader:
    """Load and manage configuration from YAML file"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.model_map = self._build_model_map()
        self.fallbacks = self._build_fallbacks()
        self._configure_proxies()
        self.default_pre_call_moderation = env_bool("GUARDRAILS_PRE_CALL_ENABLED", False)
        self.default_post_call_moderation = env_bool("GUARDRAILS_POST_CALL_ENABLED", False)
    
    def _load_config(self) -> dict:
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}
    
    def _build_model_map(self) -> Dict[str, dict]:
        """Build a map of model names to their configurations"""
        model_map = {}
        for model in self.config.get('model_list', []):
            name = model.get('model_name')
            if name:
                model_map[name] = model.get('litellm_params', {})
        return model_map
    
    def _build_fallbacks(self) -> Dict[str, List[str]]:
        """Build fallback chain from configuration"""
        fallbacks = {}
        litellm_settings = self.config.get('litellm_settings', {})
        
        for fallback_item in litellm_settings.get('fallbacks', []):
            for primary, backup_list in fallback_item.items():
                fallbacks[primary] = backup_list
        
        return fallbacks
    
    def _configure_proxies(self):
        """Configure HTTP proxies from config"""
        proxy_config = self.config.get('proxy_config', {})
        if proxy_config.get('https_proxy'):
            os.environ['HTTPS_PROXY'] = proxy_config['https_proxy']
        if proxy_config.get('http_proxy'):
            os.environ['HTTP_PROXY'] = proxy_config['http_proxy']

    def get_model_params(self, model_name: str) -> Optional[dict]:
        """Get LiteLLM parameters for a model"""
        return self.model_map.get(model_name)
    
    def get_fallback_models(self, model_name: str) -> List[str]:
        """Get fallback models for a given model"""
        fallbacks = self.fallbacks.get(model_name, [])
        default_fallbacks = self.config.get('litellm_settings', {}).get('default_fallbacks', [])
        return fallbacks + [f for f in default_fallbacks if f not in fallbacks]


# =============================================================================
# RAI Moderation Service
# =============================================================================

class RAIModerationService:
    """RAI Content Moderation Service"""
    
    def __init__(self):
        self.rai_api_url = os.getenv("RAI_API_URL")
        self.db_service = None
        
        # Configure proxies
        self.proxies = None
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        
        if http_proxy or https_proxy:
            self.proxies = {}
            if http_proxy:
                self.proxies['http'] = http_proxy
            if https_proxy:
                self.proxies['https'] = https_proxy
    
    async def initialize(self):
        """Initialize the moderation service and database connection"""
        try:
            self.db_service = get_moderation_db_service()
            await self.db_service.initialize()
            await self.db_service.ensure_table_exists()
            logger.info("RAI Moderation Service initialized with database logging")
        except Exception as e:
            logger.warning(f"Failed to initialize database service: {e}. Moderation logging disabled.")
            self.db_service = None
    
    def _create_moderation_payload(self, prompt_content: str) -> dict:
        """Create payload for RAI moderation API"""
        moderation_checks = [
            "JailBreak",
            "Toxicity",
            "Piidetct",
            "Profanity",
            "RestrictTopic"
        ]

        return {
            "AccountName": os.getenv("RAI_ACCOUNT_NAME", "None"),
            "userid": "None",
            "PortfolioName": os.getenv("RAI_PORTFOLIO_NAME", "None"),
            "lotNumber": "1",
            "Prompt": prompt_content,
            "ModerationChecks": moderation_checks,
            "ModerationCheckThresholds": {
                "PromptinjectionThreshold": 0.7,
                "JailbreakThreshold": 0.7,
                "PiientitiesConfiguredToDetect": [
                    "PERSON", "LOCATION", "DATE", "AU_ABN", "AU_ACN", "AADHAR_NUMBER",
                    "AU_MEDICARE", "AU_TFN", "CREDIT_CARD", "CRYPTO", "DATE_TIME",
                    "EMAIL_ADDRESS", "ES_NIF", "IBAN_CODE", "IP_ADDRESS",
                    "IT_DRIVER_LICENSE", "IT_FISCAL_CODE", "IT_IDENTITY_CARD",
                    "IT_PASSPORT", "IT_VAT_CODE", "MEDICAL_LICENSE", "PAN_Number",
                    "PHONE_NUMBER", "SG_NRIC_FIN", "UK_NHS", "URL", "PASSPORT",
                    "US_ITIN", "US_PASSPORT", "US_SSN", "IN_PAN"
                ],
                "PiientitiesConfiguredToBlock": [
                    "AADHAR_NUMBER", "CREDIT_CARD", "IN_PAN",
                    "PASSPORT", "PAN_Number", "PHONE_NUMBER", "IP_ADDRESS", "URL"
                ],
                "RefusalThreshold": 0.7,
                "ToxicityThresholds": {
                    "ToxicityThreshold": 0.6,
                    "SevereToxicityThreshold": 0.6,
                    "ObsceneThreshold": 0.6,
                    "ThreatThreshold": 0.6,
                    "InsultThreshold": 0.6,
                    "IdentityAttackThreshold": 0.6,
                    "SexualExplicitThreshold": 0.6
                },
                "ProfanityCountThreshold": 1,
                "RestrictedtopicDetails": {
                    "RestrictedtopicThreshold": 0.7,
                    "Restrictedtopics": [
                        "Terrorism", "Explosives", "Nudity", "Cruelty", "Cheating",
                        "Fraud", "Crime", "Hacking", "Immoral", "Unethical",
                        "Illegal", "Robbery", "Forgery", "Misinformation"
                    ]
                },
                "CustomTheme": {
                    "Themename": "string",
                    "Themethresold": 0.6,
                    "ThemeTexts": ["Text2"]
                }
            }
        }
    
    def _parse_failed_checks(self, moderation_results: dict) -> List[str]:
        """Parse failed moderation checks from results"""
        failed_checks = []
        mod_str = str(moderation_results)
        
        if 'JailBreak' in mod_str:
            failed_checks.append("potential jailbreak attempt")
        if 'Toxicity' in mod_str:
            failed_checks.append("toxic content")
        if 'Profanity' in mod_str:
            failed_checks.append("profanity")
        if 'RestrictTopic' in mod_str:
            failed_checks.append("restricted topic")
        if 'PromptInjection' in mod_str:
            failed_checks.append("prompt injection")
        
        return failed_checks
    
    async def _log_moderation_result(self, content: str, moderation_result: dict, check_type: str = "pre-call"):
        """Log moderation result to database"""
        try:
            if self.db_service:
                record_id = await self.db_service.save_moderation_log(
                    check_type=check_type,
                    content=content,
                    moderation_result=moderation_result
                )
                if record_id:
                    logger.debug(f"Moderation log saved with ID: {record_id}")
        except Exception as e:
            logger.error(f"Error logging moderation result: {e}")
    
    async def moderate_content(self, content: str, check_type: str = "pre-call") -> tuple[bool, Optional[str]]:
        """
        Moderate content using RAI API
        
        Returns:
            tuple: (passed: bool, error_message: Optional[str])
        """
        if not self.rai_api_url:
            logger.warning("RAI_API_URL not configured, skipping moderation")
            return True, None
        
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        payload = self._create_moderation_payload(content)
        
        try:
            response = requests.post(
                self.rai_api_url,
                json=payload,
                headers=headers,
                proxies=self.proxies,
                verify=False,
                timeout=30
            )
            response.raise_for_status()
            resp = response.json()
            
            logger.debug(f"RAI API Response: {resp}")
            
            # Log to database
            await self._log_moderation_result(content, resp, check_type=check_type)
            
            mod_results = resp.get('moderationResults', {})
            summary = mod_results.get('summary', {})
            status = summary.get('status', 'UNKNOWN')
            
            if status == "PASSED":
                return True, None
            else:
                failed_checks = self._parse_failed_checks(mod_results)
                violation_message = ", ".join(failed_checks) if failed_checks else "policy violation"
                return False, f"Content flagged for: {violation_message}"
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling RAI API: {e}")
            raise HTTPException(
                status_code=503,
                detail={"error": f"Moderation Service Unavailable: {str(e)}"}
            )
        except Exception as e:
            logger.error(f"Unexpected error in moderation: {e}")
            raise HTTPException(
                status_code=500,
                detail={"error": f"Moderation error: {str(e)}"}
            )
    
    async def pre_call_moderation(self, messages: List[Message]) -> tuple[bool, Optional[str]]:
        """
        Perform pre-call moderation on all messages
        
        Returns:
            tuple: (passed: bool, error_message: Optional[str])
        """
        for message in messages:
            if message.role in ["user", "human", "system", "tool"]:
                passed, error = await self.moderate_content(
                    message.content,
                    check_type=f"pre-call-{message.role}"
                )
                if not passed:
                    return False, error
        
        return True, None
    
    async def post_call_moderation(self, response_content: str) -> tuple[bool, Optional[str]]:
        """Perform post-call moderation on response"""
        return await self.moderate_content(response_content, check_type="post-call")


# =============================================================================
# LiteLLM Service
# =============================================================================

class LiteLLMService:
    """Service for making LLM calls with fallback support"""
    
    def __init__(self, config: ConfigLoader):
        self.config = config
    
    async def chat_completion(
        self,
        model: str,
        messages: List[dict],
        **kwargs
    ) -> Any:
        """
        Make a chat completion request with fallback support
        """
        models_to_try = [model] + self.config.get_fallback_models(model)
        last_error = None
        is_ollama_error = False
        
        for attempt_model in models_to_try:
            model_params = self.config.get_model_params(attempt_model)
            
            if not model_params:
                logger.warning(f"Model {attempt_model} not found in configuration")
                continue
            
            is_ollama = model_params.get('is_ollama', False) or attempt_model.startswith('ollama/')
            
            try:
                # Prepare litellm parameters
                litellm_model = model_params.get('model')
                api_base = model_params.get('api_base')
                api_key = model_params.get('api_key')
                
                logger.info(f"Attempting: {attempt_model} → deployment: {litellm_model}")
                
                response = await acompletion(
                    model=litellm_model,
                    messages=messages,
                    api_base=api_base,
                    api_key=api_key,
                    **kwargs
                )
                
                # Log the exact deployment used by LiteLLM's load balancer
                actual_model_used = getattr(response, 'model', litellm_model)
                logger.info(f"✓ Success: {attempt_model} → {actual_model_used}")
                
                return response, attempt_model
            
            except requests.exceptions.ConnectionError as e:
                if is_ollama:
                    logger.warning(f"Ollama model {attempt_model} unavailable (connection error): {e}")
                    is_ollama_error = True
                else:
                    logger.warning(f"Model {attempt_model} failed (connection error): {e}")
                last_error = e
                continue
            
            except Exception as e:
                error_msg = str(e).lower()
                if is_ollama and ('connection' in error_msg or 'refused' in error_msg or 'timeout' in error_msg):
                    logger.warning(f"Ollama model {attempt_model} unavailable: {e}")
                    is_ollama_error = True
                else:
                    logger.warning(f"Model {attempt_model} failed: {e}")
                last_error = e
                continue
        
        # All models failed
        error_detail = f"All models failed. Last error: {str(last_error)}"
        if is_ollama_error:
            error_detail = f"Ollama server may be unavailable. {error_detail}"
        
        raise HTTPException(
            status_code=503,
            detail={"error": error_detail}
        )


# =============================================================================
# Ollama Service
# =============================================================================

class OllamaService:
    """Service for discovering and using local Ollama models"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.models: Dict[str, dict] = {}
        self.available = False
    
    async def discover_models(self) -> Dict[str, dict]:
        """
        Discover available Ollama models by querying the local server.
        Returns a dict of model_name -> litellm_params
        """
        try:
            # Query Ollama API for available models
            # Bypass proxy for localhost/local connections
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5,
                proxies={'http': None, 'https': None}  # Bypass proxy for local Ollama
            )
            
            if response.status_code == 403:
                logger.info("Ollama server returned 403 - may need to check firewall or Ollama configuration")
                return {}
            
            if response.status_code != 200:
                logger.info(f"Ollama server returned status {response.status_code}")
                return {}
            
            data = response.json()
            models = data.get('models', [])
            
            if not models:
                logger.info("No Ollama models found")
                return {}
            
            # Build model map for discovered models
            discovered = {}
            for model in models:
                model_name = model.get('name', '')
                if model_name:
                    # Remove tag if present (e.g., "llama2:latest" -> use full name)
                    display_name = f"ollama/{model_name.replace(':latest', '')}"
                    discovered[display_name] = {
                        'model': f"ollama/{model_name}",
                        'api_base': self.base_url,
                        'api_key': 'ollama',  # Ollama doesn't need an API key
                        'is_ollama': True
                    }
            
            self.models = discovered
            self.available = len(discovered) > 0
            
            if discovered:
                logger.info(f"Discovered {len(discovered)} Ollama models: {list(discovered.keys())}")
            
            return discovered
        
        except requests.exceptions.ConnectionError:
            logger.info("Ollama server not available at " + self.base_url)
            return {}
        except requests.exceptions.Timeout:
            logger.info("Ollama server timed out")
            return {}
        except Exception as e:
            logger.warning(f"Error discovering Ollama models: {e}")
            return {}
    
    def get_model_params(self, model_name: str) -> Optional[dict]:
        """Get parameters for an Ollama model"""
        return self.models.get(model_name)
    
    def is_ollama_model(self, model_name: str) -> bool:
        """Check if a model is an Ollama model"""
        return model_name in self.models or model_name.startswith('ollama/')


# =============================================================================
# Application Setup
# =============================================================================

# Global instances
config_loader: Optional[ConfigLoader] = None
moderation_service: Optional[RAIModerationService] = None
litellm_service: Optional[LiteLLMService] = None
ollama_service: Optional[OllamaService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    global config_loader, moderation_service, litellm_service, ollama_service
    
    # Startup
    logger.info("Starting LiteLLM FastAPI Server...")
    
    config_loader = ConfigLoader()
    moderation_service = RAIModerationService()
    litellm_service = LiteLLMService(config_loader)
    ollama_service = OllamaService()
    
    # Discover Ollama models
    ollama_models = await ollama_service.discover_models()
    if ollama_models:
        # Add Ollama models to config_loader's model_map
        config_loader.model_map.update(ollama_models)
        logger.info(f"Added {len(ollama_models)} Ollama models to available models")
    
    await moderation_service.initialize()
    
    logger.info(f"Loaded {len(config_loader.model_map)} models from configuration")
    logger.info(
        "RAI moderation defaults (.env): "
        f"GUARDRAILS_PRE_CALL_ENABLED={config_loader.default_pre_call_moderation}, "
        f"GUARDRAILS_POST_CALL_ENABLED={config_loader.default_post_call_moderation}"
    )
    logger.info("Server ready!")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if moderation_service and moderation_service.db_service:
        await moderation_service.db_service.close()


app = FastAPI(
    title="LiteLLM FastAPI Server",
    description="OpenAI-compatible API server with RAI moderation",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/v1/models")
@app.get("/models")
async def list_models():
    """List available models"""
    models = []
    for model_name, params in config_loader.model_map.items():
        model_info = {
            "id": model_name,
            "object": "model",
            "owned_by": "ollama" if params.get('is_ollama') else "organization"
        }
        models.append(model_info)
    
    return {"object": "list", "data": models}


# @app.post("/v1/models/refresh-ollama")
# @app.post("/models/refresh-ollama")
# async def refresh_ollama_models():
#     """Refresh the list of available Ollama models"""
#     if ollama_service:
#         # Remove existing Ollama models
#         ollama_models_to_remove = [
#             name for name, params in config_loader.model_map.items() 
#             if params.get('is_ollama')
#         ]
#         for name in ollama_models_to_remove:
#             del config_loader.model_map[name]
        
#         # Discover new models
#         new_models = await ollama_service.discover_models()
#         if new_models:
#             config_loader.model_map.update(new_models)
        
#         return {
#             "status": "success",
#             "ollama_models": list(new_models.keys()) if new_models else [],
#             "total_models": len(config_loader.model_map)
#         }
    
#     return {"status": "ollama_not_configured", "ollama_models": []}


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
@app.post("/openai/deployments/{deployment}/chat/completions")
async def chat_completions(request: ChatCompletionRequest, deployment: str = None):
    """
    OpenAI-compatible chat completions endpoint
    
    Features:
    - Pre-call RAI moderation
    - Model routing with fallbacks
    - Post-call moderation
    - Database logging
    
    Supports both OpenAI and Azure OpenAI API formats:
    - /v1/chat/completions (OpenAI)
    - /chat/completions (OpenAI)
    - /openai/deployments/{deployment}/chat/completions (Azure)
    """
    # Use deployment name as model if provided via Azure-style endpoint
    model = deployment if deployment else request.model
    
    if not model:
        raise HTTPException(
            status_code=400,
            detail={"error": "Model must be specified either in request body or URL path"}
        )
    
    pre_mod = (
        request.pre_call_moderation
        if request.pre_call_moderation is not None
        else config_loader.default_pre_call_moderation
    )
    post_mod = (
        request.post_call_moderation
        if request.post_call_moderation is not None
        else config_loader.default_post_call_moderation
    )

    # Pre-call moderation (if enabled)
    if pre_mod:
        passed, error = await moderation_service.pre_call_moderation(request.messages)
        if not passed:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": error,
                        "type": "content_policy_violation",
                        "code": "content_filter"
                    }
                }
            )
    
    # Prepare messages for litellm
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    
    # Build kwargs
    kwargs = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.stop is not None:
        kwargs["stop"] = request.stop
    if request.presence_penalty is not None:
        kwargs["presence_penalty"] = request.presence_penalty
    if request.frequency_penalty is not None:
        kwargs["frequency_penalty"] = request.frequency_penalty
    
    # Handle streaming
    if request.stream:
        return await stream_chat_completion(model, messages, kwargs)
    
    # Make LLM call
    response, used_model = await litellm_service.chat_completion(
        model=model,
        messages=messages,
        **kwargs
    )
    
    # Post-call moderation (if enabled)
    if post_mod and response.choices and response.choices[0].message:
        response_content = response.choices[0].message.content
        passed, error = await moderation_service.post_call_moderation(response_content)
        if not passed:
            logger.warning(f"Response failed post-call moderation: {error}")
            # Optionally block the response or just log
    
    # Convert to our response format
    return {
        "id": response.id,
        "object": "chat.completion",
        "created": response.created,
        "model": used_model,
        "choices": [
            {
                "index": choice.index,
                "message": {
                    "role": choice.message.role,
                    "content": choice.message.content
                },
                "finish_reason": choice.finish_reason
            }
            for choice in response.choices
        ],
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0
        }
    }


async def stream_chat_completion(model: str, messages: List[dict], kwargs: dict):
    """Handle streaming chat completions"""
    
    async def generate():
        models_to_try = [model] + config_loader.get_fallback_models(model)
        last_error = None
        is_ollama_error = False
        
        for attempt_model in models_to_try:
            model_params = config_loader.get_model_params(attempt_model)
            if not model_params:
                continue
            
            is_ollama = model_params.get('is_ollama', False) or attempt_model.startswith('ollama/')
            
            try:
                litellm_model = model_params.get('model')
                api_base = model_params.get('api_base')
                api_key = model_params.get('api_key')
                
                logger.info(f"Attempting stream: {attempt_model} → {litellm_model}")
                
                response = await acompletion(
                    model=litellm_model,
                    messages=messages,
                    api_base=api_base,
                    api_key=api_key,
                    stream=True,
                    **kwargs
                )
                
                # Track if we've logged the actual model used
                logged_model = False
                
                async for chunk in response:
                    # Log the actual deployment used (only once)
                    if not logged_model:
                        actual_model_used = getattr(chunk, 'model', litellm_model)
                        logger.info(f"✓ Streaming: {attempt_model} → {actual_model_used}")
                        logged_model = True
                    
                    chunk_data = {
                        "id": chunk.id,
                        "object": "chat.completion.chunk",
                        "created": chunk.created,
                        "model": attempt_model,
                        "choices": [
                            {
                                "index": choice.index,
                                "delta": {
                                    "role": getattr(choice.delta, 'role', None),
                                    "content": getattr(choice.delta, 'content', None)
                                },
                                "finish_reason": choice.finish_reason
                            }
                            for choice in chunk.choices
                        ]
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"
                
                yield "data: [DONE]\n\n"
                return
            
            except Exception as e:
                error_msg = str(e).lower()
                if is_ollama and ('connection' in error_msg or 'refused' in error_msg or 'timeout' in error_msg):
                    logger.warning(f"Ollama model {attempt_model} unavailable (streaming): {e}")
                    is_ollama_error = True
                else:
                    logger.warning(f"Streaming failed for {attempt_model}: {e}")
                last_error = e
                continue
        
        # All models failed
        error_message = f"All models failed. Last error: {str(last_error)}"
        if is_ollama_error:
            error_message = f"Ollama server may be unavailable. {error_message}"
        error_data = {"error": {"message": error_message, "type": "server_error"}}
        yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/v1/completions")
@app.post("/completions")
async def completions(request: Request):
    """Legacy completions endpoint - converts to chat format"""
    body = await request.json()
    
    # Convert to chat format
    prompt = body.get("prompt", "")
    messages = [{"role": "user", "content": prompt}]
    
    chat_request = ChatCompletionRequest(
        model=body.get("model"),
        messages=[Message(role="user", content=prompt)],
        temperature=body.get("temperature"),
        max_tokens=body.get("max_tokens"),
        stream=body.get("stream", False)
    )
    
    return await chat_completions(chat_request)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "4000"))
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║           LiteLLM FastAPI Server (No Prisma)                  ║
╠═══════════════════════════════════════════════════════════════╣
║  Server starting at http://{host}:{port}                        ║
║  API Docs: http://{host}:{port}/docs                            ║
║                                                               ║
║  Features:                                                    ║
║  - OpenAI-compatible API                                      ║
║  - RAI Content Moderation                                     ║
║  - Model fallbacks                                            ║
║  - PostgreSQL logging (via asyncpg)                           ║
║  - Auto-discovery of local Ollama models                      ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
