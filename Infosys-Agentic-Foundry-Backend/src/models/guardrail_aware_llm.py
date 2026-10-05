"""
Guardrail-Aware LLM Wrappers

This module provides wrapper classes that extend LangChain LLM classes to handle
LiteLLM guardrail errors gracefully. These wrappers catch and process guardrail
violations, providing better error messages and logging.

Token/cost tracing is covered for all invocation paths:
- async non-streaming  (_agenerate)
- async streaming      (_astream)
- sync  non-streaming  (_generate)
- sync  streaming      (_stream)
"""

import asyncio
import threading
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

# Thread-local storage for request_id correlation
# Fallback mechanism when SessionContext is not accessible
_request_id_context = threading.local()

def _get_or_create_request_id(user_id: str = 'system') -> str:
    """
    Get or create a request_id for the current thread/async context.
    This serves as a fallback when SessionContext is not accessible.
    
    Returns:
        str: The correlation request_id for this request
    """
    import time
    import uuid
    
    # Try to get from thread-local storage first
    if hasattr(_request_id_context, 'request_id') and _request_id_context.request_id:
        return _request_id_context.request_id
    
    # Generate a new one if not found
    request_id = f"req_{str(uuid.uuid4())[:8]}_{user_id[:20]}_{int(time.time())}"
    _request_id_context.request_id = request_id
    return request_id

def _set_request_id(request_id: str) -> None:
    """Store request_id in thread-local storage."""
    _request_id_context.request_id = request_id

def _clear_request_id() -> None:
    """Clear request_id from thread-local storage."""
    if hasattr(_request_id_context, 'request_id'):
        delattr(_request_id_context, 'request_id')

# Lazily captured reference to the main event loop.
# Set the first time any async LLM method runs so that sync methods called
# from thread executors (e.g. LangGraph formatter node) can still schedule
# async logging via asyncio.run_coroutine_threadsafe.
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _capture_event_loop() -> None:
    """Record the running event loop on first async use (called from _agenerate / _astream)."""
    global _main_event_loop
    if _main_event_loop is None:
        try:
            _main_event_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.language_models.chat_models import BaseChatModel
from openai import APIError, APIStatusError
import json

from telemetry_wrapper import logger as log


# ---------------------------------------------------------------------------
# Helper: read agent / session context from the thread-local SessionContext
# ---------------------------------------------------------------------------

def _ctx_from_session() -> Dict[str, Any]:
    """
    Build an agent-context dict from telemetry_wrapper.SessionContext.
    Returns an empty dict on any failure so callers never crash.

    SessionContext.get() tuple layout:
      0: user_id  1: session_id  2: user_session  3: agent_id  4: agent_name
      5: tool_id  6: tool_name   7: model_used    ...  21: department_name
    """
    try:
        from telemetry_wrapper import SessionContext
        ctx = SessionContext.get()
        def _v(val):
            return val if val != 'Unassigned' else None
        department = _v(ctx[21]) if len(ctx) > 21 else None
        return {
            'user_id':         _v(ctx[0]),
            'session_id':      _v(ctx[1]),
            'agent_id':        _v(ctx[3]),
            'agent_name':      _v(ctx[4]),
            'department_name': department,
        }
    except Exception:
        return {}


class GuardrailError(Exception):
    """Custom exception for guardrail violations"""

    def __init__(
        self,
        message: str,
        guardrail_type: str = "UNKNOWN",
        violations: List[str] = None,
        original_error: Exception = None,
        details: Dict[str, Any] = None
    ):
        super().__init__(message)
        self.message = message
        self.guardrail_type = guardrail_type
        self.violations = violations or []
        self.original_error = original_error
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses"""
        return {
            "error": "GuardrailViolation",
            "message": self.message,
            "guardrail_type": self.guardrail_type,
            "violations": self.violations,
            "details": self.details
        }


class GuardrailMixin:
    """
    Mixin class that provides guardrail error handling capabilities.

    This mixin intercepts API errors and checks if they're guardrail violations,
    converting them to GuardrailError for better error handling.
    """

    def _handle_guardrail_error(self, error: Exception) -> Exception:
        if isinstance(error, APIStatusError):
            try:
                if hasattr(error, 'response') and error.response:
                    status_code = error.status_code

                    if status_code == 400:
                        error_body = None
                        if hasattr(error, 'body'):
                            error_body = error.body
                        elif hasattr(error.response, 'json'):
                            try:
                                error_body = error.response.json()
                            except:
                                pass

                        if error_body:
                            if isinstance(error_body, dict):
                                detail = error_body.get('detail', {})

                                if isinstance(detail, dict):
                                    guardrail_type = detail.get('guardrail_type')
                                    if guardrail_type:
                                        violations = detail.get('violations', [])
                                        message = detail.get('message', str(error))
                                        log.warning(f"Guardrail violation detected: {guardrail_type} - {violations}")
                                        return GuardrailError(
                                            message=message,
                                            guardrail_type=guardrail_type,
                                            violations=violations,
                                            original_error=error,
                                            details=detail
                                        )

                                elif detail.get('error') == 'Content Moderation Failed':
                                    return GuardrailError(
                                        message=detail.get('message', str(error)),
                                        guardrail_type=detail.get('guardrail_type', 'CONTENT_MODERATION'),
                                        violations=detail.get('violations', []),
                                        original_error=error,
                                        details=detail
                                    )

                                error_type = error_body.get('type', '')
                                error_code = error_body.get('code', '')
                                if error_type == 'content_policy_violation' or error_code in ('content_filter', 'content_policy_violation'):
                                    message = error_body.get('message', str(error))
                                    log.warning(f"RAI content policy violation detected: {message}")
                                    return GuardrailError(
                                        message=message,
                                        guardrail_type='RAI_CONTENT_POLICY_VIOLATION',
                                        violations=[message],
                                        original_error=error,
                                        details=error_body
                                    )

                                error_message = error_body.get('message', '') or ''
                                if error_message:
                                    msg_lower = error_message.lower()
                                    if any(kw in msg_lower for kw in (
                                        'contentpolicyviolation', 'content_policy_violation',
                                        'was flagged for:', 'content_filter',
                                        'content management policy',
                                    )):
                                        actual_message = error_message
                                        for msg_prefix in [
                                            'litellm.BadRequestError: litellm.ContentPolicyViolationError: ',
                                            'litellm.ContentPolicyViolationError: ',
                                            'ContentPolicyViolationError: ',
                                            'litellm.BadRequestError: ',
                                        ]:
                                            if msg_prefix in actual_message:
                                                actual_message = actual_message.split(msg_prefix, 1)[-1]
                                                break
                                        log.warning(f"Content policy violation detected from error message: {actual_message}")
                                        return GuardrailError(
                                            message=actual_message,
                                            guardrail_type='CONTENT_POLICY_VIOLATION',
                                            violations=[actual_message],
                                            original_error=error,
                                            details=error_body
                                        )

                                nested_error = error_body.get('error', {})
                                if isinstance(nested_error, dict):
                                    nested_type = nested_error.get('type', '') or ''
                                    nested_code = nested_error.get('code', '') or ''
                                    nested_message = nested_error.get('message', '') or ''

                                    if nested_type == 'content_policy_violation' or nested_code in ('content_filter', 'content_policy_violation'):
                                        message = nested_error.get('message', str(error))
                                        log.warning(f"RAI content policy violation detected (nested): {message}")
                                        return GuardrailError(
                                            message=message,
                                            guardrail_type='RAI_CONTENT_POLICY_VIOLATION',
                                            violations=[message],
                                            original_error=error,
                                            details=nested_error
                                        )

                                    if 'contentpolicyviolation' in nested_message.lower():
                                        actual_message = nested_message
                                        for msg_prefix in [
                                            'litellm.BadRequestError: litellm.ContentPolicyViolationError: ',
                                            'litellm.ContentPolicyViolationError: ',
                                            'ContentPolicyViolationError: ',
                                            'litellm.BadRequestError: ',
                                        ]:
                                            if msg_prefix in actual_message:
                                                actual_message = actual_message.split(msg_prefix, 1)[-1]
                                                break
                                        log.warning(f"Content policy violation detected from message: {actual_message}")
                                        return GuardrailError(
                                            message=actual_message,
                                            guardrail_type='CONTENT_POLICY_VIOLATION',
                                            violations=[actual_message],
                                            original_error=error,
                                            details=nested_error
                                        )
            except Exception as e:
                log.error(f"Error while parsing guardrail error: {e}")

        return error

    def _log_guardrail_error(self, error: GuardrailError, context: str = ""):
        log.warning(
            f"Guardrail violation {context}: "
            f"Type={error.guardrail_type}, "
            f"Violations={error.violations}, "
            f"Message={error.message}"
        )


class TokenLoggingMixin:
    """
    Mixin providing token/cost logging via the registered post-completion hook system.

    Covers every invocation path:
    - _agenerate / _generate  (non-streaming)
    - _astream  / _stream     (streaming)
    """

    def _get_model_name(self) -> Optional[str]:
        """Resolve the deployment/model name from instance attributes."""
        return (
            getattr(self, 'azure_deployment', None)
            or getattr(self, 'deployment_name', None)
            or getattr(self, 'model', None)
            or getattr(self, 'model_name', None)
        )

    def _inject_session_headers(self, kwargs: dict) -> dict:
        """Inject agent/session identifiers and guardrail type as HTTP headers."""
        try:
            extra_headers = kwargs.get('extra_headers', {})
            ctx = _ctx_from_session()
            agent_id = ctx.get('agent_id')
            if agent_id:
                extra_headers['x-agent-id'] = agent_id
                if ctx.get('agent_name'):
                    extra_headers['x-agent-name'] = ctx['agent_name']
                if ctx.get('session_id'):
                    extra_headers['x-session-id'] = ctx['session_id']
                if ctx.get('user_id'):
                    extra_headers['x-user-id'] = ctx['user_id']

            # Guardrail provider header
            from src.utils.guardrail_helpers import guardrail_type_ctx, guardrail_registry
            g_type = guardrail_type_ctx.get(None)
            if g_type and g_type != "none":
                extra_headers['x-guardrail-type'] = g_type
                extra_headers['x-guardrail-provider'] = guardrail_registry.get_proxy_provider(g_type)

            kwargs['extra_headers'] = extra_headers
        except Exception as exc:
            log.debug(f"[TokenLogging] Could not inject session headers: {exc}")
        return kwargs

    async def _fire_hooks_from_result(self, result: ChatResult) -> None:
        """Extract token usage from a completed ChatResult and fire all registered hooks."""
        _capture_event_loop()
        try:
            from src.models.azure_ai_model_service import _post_completion_hooks

            if not _post_completion_hooks:
                return

            model_name = self._get_model_name()
            token_usage = None

            if hasattr(result, 'llm_output') and result.llm_output:
                token_usage = result.llm_output.get('token_usage')
                model_name = result.llm_output.get('model_name') or model_name

            if not token_usage:
                log.warning("⚠️ [TokenLogging] No token_usage found in ChatResult.llm_output")
                return

            await self._dispatch_hooks(token_usage, model_name)

        except Exception as exc:
            log.error(f"❌ [TokenLogging] _fire_hooks_from_result failed: {exc}", exc_info=True)

    async def _fire_hooks_from_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cached_tokens: int = 0,
        model_name: Optional[str] = None,
    ) -> None:
        """Fire hooks directly from token counts (e.g., accumulated from a stream)."""
        _capture_event_loop()
        if total_tokens == 0:
            log.debug("[TokenLogging] Skipping hook: total_tokens == 0")
            return

        try:
            from src.models.azure_ai_model_service import _post_completion_hooks

            if not _post_completion_hooks:
                return

            token_usage = {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': total_tokens,
                'prompt_tokens_details': {'cached_tokens': cached_tokens} if cached_tokens else {},
            }
            await self._dispatch_hooks(token_usage, model_name or self._get_model_name())

        except Exception as exc:
            log.error(f"❌ [TokenLogging] _fire_hooks_from_usage failed: {exc}", exc_info=True)

    async def _dispatch_hooks(
        self,
        token_usage: Dict[str, Any],
        model_name: Optional[str],
    ) -> None:
        """
        Wrap token counts in a standardised response object and call every registered hook.
        Agent/session context is read from SessionContext inside each hook — no need to
        pass a separate context dict here.
        """
        from src.models.azure_ai_model_service import _post_completion_hooks

        class _Metrics:
            def __init__(self, u: dict):
                self.prompt_tokens = u.get('prompt_tokens', 0)
                self.completion_tokens = u.get('completion_tokens', 0)
                self.total_tokens = u.get('total_tokens', 0)
                pd = u.get('prompt_tokens_details') or {}
                self.cached_tokens = pd.get('cached_tokens', 0)
                self.prompt_tokens_details = (
                    type('_pd', (), {'cached_tokens': self.cached_tokens})()
                    if pd else None
                )

        class _Response:
            def __init__(self, u: dict, m: Optional[str]):
                self.usage = _Metrics(u)
                self.model = m

        resp = _Response(token_usage, model_name)
        # Pass context dict so hook can use it as primary source (falls back to
        # SessionContext internally if values are missing).
        ctx = _ctx_from_session()
        ctx['model_name'] = model_name

        log.info(
            f"🪝 [TokenLogging] Firing {len(_post_completion_hooks)} hook(s) — "
            f"model={model_name}, total_tokens={resp.usage.total_tokens}"
        )
        for hook in _post_completion_hooks:
            try:
                await hook(resp, ctx)
            except Exception as hook_exc:
                log.error(f"❌ [TokenLogging] Hook '{hook.__name__}': {hook_exc}", exc_info=True)

    def _schedule_async_logging(self, coro) -> None:
        """
        Schedule an async logging coroutine from a synchronous method.

        Two execution contexts are handled:
        1. Called directly from an async context (same thread as event loop)
           → uses loop.create_task() for zero-overhead fire-and-forget.
        2. Called from a thread executor (e.g. LangGraph formatter node run via
           asyncio.to_thread) where get_running_loop() raises RuntimeError
           → falls back to asyncio.run_coroutine_threadsafe() using the main
             event loop reference captured on the first async LLM call.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # We are in a worker thread. Use the captured main event loop.
            loop = _main_event_loop
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, loop)
            else:
                coro.close()
                log.debug("[TokenLogging] No event loop available — sync token logging skipped")

    @staticmethod
    def _usage_from_chunk(chunk: ChatGeneration) -> Optional[Dict[str, int]]:
        """
        Extract token usage from a streaming ChatGenerationChunk.

        Returns a dict with keys input_tokens / output_tokens / total_tokens, or None.
        Checks AIMessageChunk.usage_metadata (langchain-openai >= 0.1 with stream_usage=True)
        and falls back to generation_info for older/alternative formats.
        """
        msg = getattr(chunk, 'message', None)
        if msg is not None:
            um = getattr(msg, 'usage_metadata', None)
            if um:
                def _g(o, k):
                    return (o.get(k) if isinstance(o, dict) else getattr(o, k, None)) or 0
                it = _g(um, 'input_tokens')
                ot = _g(um, 'output_tokens')
                tt = _g(um, 'total_tokens')
                if it or ot or tt:
                    return {'input_tokens': it, 'output_tokens': ot, 'total_tokens': tt}

        # Fallback: generation_info (older / alternative format)
        gi = getattr(chunk, 'generation_info', None)
        if isinstance(gi, dict):
            u = gi.get('usage')
            if isinstance(u, dict):
                pt = u.get('prompt_tokens', 0) or 0
                ct = u.get('completion_tokens', 0) or 0
                tt = u.get('total_tokens', 0) or (pt + ct)
                if pt or ct or tt:
                    return {'input_tokens': pt, 'output_tokens': ct, 'total_tokens': tt}

        return None


class GuardrailAzureChatOpenAI(GuardrailMixin, TokenLoggingMixin, AzureChatOpenAI):
    """
    Extension of AzureChatOpenAI that handles LiteLLM guardrail errors and logs
    token usage across all invocation paths.
    """

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override _generate to handle guardrail errors, inject agent context, and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        try:
            result = super()._generate(messages, stop, run_manager, **kwargs)
            self._schedule_async_logging(self._fire_hooks_from_result(result))
            return result
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="generate")
            raise error

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override async _agenerate to handle guardrail errors and trigger token logging hooks."""
        kwargs = self._inject_session_headers(kwargs)

        try:
            result = await super()._agenerate(messages, stop, run_manager, **kwargs)
            await self._fire_hooks_from_result(result)
            return result
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="async_generate")
            raise error

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        """Override _stream to handle guardrail errors, inject agent context, and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        last_usage = None
        try:
            for chunk in super()._stream(messages, stop, run_manager, **kwargs):
                u = self._usage_from_chunk(chunk)
                if u:
                    last_usage = u
                yield chunk
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="stream")
            raise error
        finally:
            if last_usage:
                self._schedule_async_logging(
                    self._fire_hooks_from_usage(
                        prompt_tokens=last_usage['input_tokens'],
                        completion_tokens=last_usage['output_tokens'],
                        total_tokens=last_usage['total_tokens'],
                    )
                )

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGeneration]:
        """Override async _astream to handle guardrail errors and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        last_usage = None
        try:
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                u = self._usage_from_chunk(chunk)
                if u:
                    last_usage = u
                yield chunk
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="async_stream")
            raise error
        finally:
            if last_usage:
                await self._fire_hooks_from_usage(
                    prompt_tokens=last_usage['input_tokens'],
                    completion_tokens=last_usage['output_tokens'],
                    total_tokens=last_usage['total_tokens'],
                )


class GuardrailChatOpenAI(GuardrailMixin, TokenLoggingMixin, ChatOpenAI):
    """
    Extension of ChatOpenAI that handles LiteLLM guardrail errors and logs token usage
    across all invocation paths.

    Similar to GuardrailAzureChatOpenAI but for standard OpenAI endpoints
    (including LiteLLM proxy with OpenAI-compatible interface).
    """

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override _generate to handle guardrail errors and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        try:
            result = super()._generate(messages, stop, run_manager, **kwargs)
            self._schedule_async_logging(self._fire_hooks_from_result(result))
            return result
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="generate")
            raise error

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override async _agenerate to handle guardrail errors and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        try:
            result = await super()._agenerate(messages, stop, run_manager, **kwargs)
            await self._fire_hooks_from_result(result)
            return result
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="async_generate")
            raise error
        
        log.info(f"🔵 LLM Request Started (async): {request_id} | User: {user_id} | Model: {model_name}")

        try:
            result = await super()._agenerate(messages, stop, run_manager, **kwargs)
            
            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Track successful request
            await self._track_successful_request(
                request_id, user_id, session_id, model_name,
                duration_ms, agent_id, agent_name
            )
            
            return result
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="async_generate")
            raise error

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        """Override _stream to handle guardrail errors and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        last_usage = None
        try:
            for chunk in super()._stream(messages, stop, run_manager, **kwargs):
                u = self._usage_from_chunk(chunk)
                if u:
                    last_usage = u
                yield chunk
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="stream")
            raise error
        finally:
            if last_usage:
                self._schedule_async_logging(
                    self._fire_hooks_from_usage(
                        prompt_tokens=last_usage['input_tokens'],
                        completion_tokens=last_usage['output_tokens'],
                        total_tokens=last_usage['total_tokens'],
                    )
                )

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGeneration]:
        """Override async _astream to handle guardrail errors and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        last_usage = None
        try:
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                u = self._usage_from_chunk(chunk)
                if u:
                    last_usage = u
                yield chunk
        except Exception as e:
            error = self._handle_guardrail_error(e)
            if isinstance(error, GuardrailError):
                self._log_guardrail_error(error, context="async_stream")
            raise error
        finally:
            if last_usage:
                await self._fire_hooks_from_usage(
                    prompt_tokens=last_usage['input_tokens'],
                    completion_tokens=last_usage['output_tokens'],
                    total_tokens=last_usage['total_tokens'],
                )


def create_guardrail_llm(
    base_class: type,
    **kwargs
) -> Union[GuardrailAzureChatOpenAI, GuardrailChatOpenAI]:
    """
    Factory function to create a guardrail LLM instance.

    Args:
        base_class: The base LLM class (AzureChatOpenAI or ChatOpenAI)
        **kwargs: Keyword arguments to pass to the LLM constructor

    Returns:
        A guardrail instance of the specified LLM class
    """
    if base_class == AzureChatOpenAI or issubclass(base_class, AzureChatOpenAI):
        return GuardrailAzureChatOpenAI(**kwargs)
    elif base_class == ChatOpenAI or issubclass(base_class, ChatOpenAI):
        return GuardrailChatOpenAI(**kwargs)
    else:
        raise ValueError(f"Unsupported LLM class: {base_class}")


class TokenLoggingAzureChatOpenAI(TokenLoggingMixin, AzureChatOpenAI):
    """
    Extension of AzureChatOpenAI that triggers token usage logging hooks across all
    invocation paths (async/sync, streaming/non-streaming).
    """

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override async _agenerate to trigger token logging hooks and track requests."""
        import time
        import traceback
        from src.utils.llm_request_tracker import generate_llm_request_id, log_llm_request, get_call_origin_info
        
        # Get context for request tracking
        ctx = _ctx_from_session()
        user_id = ctx.get('user_id') or 'system'
        session_id = ctx.get('session_id') or 'unknown'
        agent_id = ctx.get('agent_id')
        agent_name = ctx.get('agent_name')
        department_name = ctx.get('department_name')
        model_name = self._get_model_name() or 'unknown'
        
        # Get or generate request_id (correlation ID for all LLM calls in this user request)
        # Three-tier fallback strategy:
        # 1. Try SessionContext (primary)
        # 2. Try thread-local storage (fallback for inaccessible SessionContext)
        # 3. Generate new ID (last resort)
        from telemetry_wrapper import SessionContext
        request_id = None
        session_context_available = False
        
        # Tier 1: Try SessionContext
        try:
            session_tuple = SessionContext.get()
            # Try to get existing request_id from session context (index 20, newly added)
            request_id = session_tuple[20] if len(session_tuple) > 20 and session_tuple[20] != 'Unassigned' else None
            session_context_available = True
            if request_id:
                log.debug(f"✅ [REQUEST_ID] Retrieved from SessionContext: {request_id}")
        except Exception as e:
            log.debug(f"⚠️ [REQUEST_ID] SessionContext not accessible: {e}")
            request_id = None
        
        # Tier 2: Try thread-local storage (fallback)
        if not request_id:
            if hasattr(_request_id_context, 'request_id') and _request_id_context.request_id:
                request_id = _request_id_context.request_id
                log.debug(f"✅ [REQUEST_ID] Retrieved from thread-local storage: {request_id}")
        
        # Tier 3: Generate new request_id (first LLM call or SessionContext unavailable)
        if not request_id:
            import uuid
            request_id = f"req_{str(uuid.uuid4())[:8]}_{user_id[:20]}_{int(time.time())}"
            log.info(f"🆕 [REQUEST_ID] Generated new request_id: {request_id} (SessionContext: {session_context_available})")
            
            # Persist to both SessionContext AND thread-local storage for redundancy
            # SessionContext: Primary storage (works across async context)
            if session_context_available:
                try:
                    SessionContext.set(request_id=request_id)
                    log.debug(f"✅ [REQUEST_ID] Persisted to SessionContext: {request_id}")
                except Exception as e:
                    log.warning(f"⚠️ [REQUEST_ID] Could not persist to SessionContext: {e}")
            
            # Thread-local: Fallback storage (works when SessionContext unavailable)
            try:
                _set_request_id(request_id)
                log.debug(f"✅ [REQUEST_ID] Persisted to thread-local storage: {request_id}")
            except Exception as e:
                log.warning(f"⚠️ [REQUEST_ID] Could not persist to thread-local storage: {e}")
        
        # Determine request source intelligently
        try:
            # Index 19 is call_category in the tuple
            request_source = session_tuple[19] if len(session_tuple) > 19 and session_tuple[19] != 'Unassigned' else None
        except:
            request_source = None
        
        # Fallback to inferring from context
        if not request_source:
            if agent_id:
                request_source = 'agent_inference'
            elif ctx.get('tool_id'):
                request_source = 'tool_call'
            else:
                request_source = 'direct_api_call'
        
        # Get detailed call origin information
        call_origin = get_call_origin_info()
        
        # Build request context for detailed tracking
        request_context = {
            'agent_id': agent_id,
            'agent_name': agent_name,
            'message_count': len(messages) if messages else 0,
            'has_stop_sequences': bool(stop),
            'kwargs': {k: str(v)[:100] for k, v in kwargs.items()} if kwargs else {},
            # Add detailed call origin information
            'call_origin': {
                'function': call_origin.get('function_name'),
                'file': call_origin.get('file_name'),
                'line': call_origin.get('line_number'),
                'module': call_origin.get('module_name'),
                'stack_depth': call_origin.get('stack_depth'),
                'call_chain': call_origin.get('call_stack', [])[:3]  # Top 3 functions
            }
        }
        
        # Skip expensive stack trace capture for performance
        # Only capture on failures (in except block below)
        call_stack_trace = None
        
        # Generate unique LLM call ID (unique for THIS specific LLM call)
        llm_call_id = generate_llm_request_id(user_id)
        start_time = time.time()
        
        log.info(f"🔵 LLM Request Started: {llm_call_id} (request={request_id}) | User: {user_id} | Model: {model_name} | Source: {request_source}")

        try:
            result = await super()._agenerate(messages, stop, run_manager, **kwargs)
            
            # Extract duration from Azure's latency metrics (more accurate than manual timing)
            duration_ms = None
            input_tokens = None
            output_tokens = None
            total_tokens = None
            
            if hasattr(result, 'llm_output') and result.llm_output:
                # Extract latency
                latency_checkpoint = result.llm_output.get('latency_checkpoint', {})
                if latency_checkpoint:
                    duration_ms = latency_checkpoint.get('total_duration_ms')
                    log.info(f"⏱️ [LLM_TRACKING] Extracted duration from Azure latency: {duration_ms}ms")
                
                # Extract token usage
                token_usage = result.llm_output.get('token_usage', {})
                if token_usage:
                    input_tokens = token_usage.get('prompt_tokens')
                    output_tokens = token_usage.get('completion_tokens')
                    total_tokens = token_usage.get('total_tokens')
                    log.info(f"� [LLM_TRACKING] Tokens - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")
            
            # Fallback to manual timing if Azure metrics not available
            if duration_ms is None:
                duration_ms = int((time.time() - start_time) * 1000)
                log.info(f"⏱️ [LLM_TRACKING] Using manual timing: {duration_ms}ms")
            
            # Track successful request (without full stack trace to save space)
            try:
                from src.api.app_container import app_container
                
                if app_container and app_container.llm_request_tracking_repo:
                    log.info(f"🔍 [LLM_TRACKING] Logging successful request {llm_call_id} (request={request_id})")
                    await log_llm_request(
                        repository=app_container.llm_request_tracking_repo,
                        request_id=request_id,  # Correlation ID (same for all LLM calls in this user request)
                        llm_call_id=llm_call_id,  # Unique ID for this specific LLM call
                        user_id=user_id,
                        session_id=session_id,
                        model_name=model_name,
                        status="success",
                        duration_ms=duration_ms,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        request_source=request_source,
                        request_context=request_context,  # Contains workspace_code with parsed locations
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        department_name=department_name
                    )
                    log.info(f"✅ [LLM_TRACKING] Successfully logged request {llm_call_id} (request={request_id})")
                else:
                    log.warning(f"⚠️ [LLM_TRACKING] Cannot track request - app_container or repository not available")
            except Exception as track_error:
                log.error(f"⚠️ Failed to track LLM request {llm_call_id}: {track_error}", exc_info=True)
        except Exception as e:
            # Track failed request with detailed error information
            duration_ms = int((time.time() - start_time) * 1000)
            error_type = type(e).__name__
            error_message = str(e)
            # Capture error traceback - this is the exception trace
            error_trace = traceback.format_exc()
            
            # Only capture call stack on errors (more lightweight than capturing on every call)
            call_stack_trace = ''.join(traceback.format_stack())
            
            # Combine both: call origin stack (where request came from) + error trace (what went wrong)
            combined_trace = f"=== ERROR TRACE ===\n{error_trace}\n\n=== CALL ORIGIN STACK ===\n{call_stack_trace}"
            
            log.error(f"❌ [LLM_TRACKING] Request {llm_call_id} (request={request_id}) failed: {error_type} - {error_message}")
            
            try:
                from src.api.app_container import app_container
                if app_container and app_container.llm_request_tracking_repo:
                    await log_llm_request(
                        repository=app_container.llm_request_tracking_repo,
                        request_id=request_id,  # Correlation ID (same for all LLM calls in this user request)
                        llm_call_id=llm_call_id,  # Unique ID for this specific LLM call
                        user_id=user_id,
                        session_id=session_id,
                        model_name=model_name,
                        status="failed",
                        duration_ms=duration_ms,
                        error_message=error_message,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        request_source=request_source,
                        request_context=request_context,
                        error_type=error_type,
                        stack_trace=combined_trace,
                        department_name=department_name
                    )
            except Exception as track_error:
                log.error(f"⚠️ Failed to track failed LLM request {llm_call_id}: {track_error}", exc_info=True)
            raise

        # Trigger token logging hooks
        try:
            from src.models.azure_ai_model_service import _post_completion_hooks

            if _post_completion_hooks:
                log.info(f"🪝 [TokenLoggingLLM] Found {len(_post_completion_hooks)} hooks to trigger")

                # Build context from SessionContext (replaces missing get_agent_context)
                agent_ctx = _ctx_from_session()

                token_usage = None
                model_name = None
                if hasattr(result, 'llm_output') and result.llm_output:
                    token_usage = result.llm_output.get('token_usage', None)
                    model_name = result.llm_output.get('model_name', None)
                    log.info(f"📊 [TokenLoggingLLM] Token usage from llm_output: {token_usage}")
                    log.info(f"📊 [TokenLoggingLLM] Model name from llm_output: {model_name}")

                if not model_name:
                    model_name = getattr(self, 'deployment_name', None) or getattr(self, 'model_name', None)
                    log.info(f"📊 [TokenLoggingLLM] Model name from LLM instance: {model_name}")
                else:
                    deployment_name = getattr(self, 'deployment_name', None)
                    if deployment_name:
                        log.info(f"📊 [TokenLoggingLLM] Overriding model name '{model_name}' with deployment name '{deployment_name}'")
                        model_name = deployment_name

                if token_usage:
                    class TokenUsageMetrics:
                        def __init__(self, usage_dict):
                            self.prompt_tokens = usage_dict.get('prompt_tokens', 0)
                            self.completion_tokens = usage_dict.get('completion_tokens', 0)
                            self.total_tokens = usage_dict.get('total_tokens', 0)
                            prompt_details = usage_dict.get('prompt_tokens_details', {})
                            self.cached_tokens = prompt_details.get('cached_tokens', 0) if prompt_details else 0
                            if prompt_details:
                                self.prompt_tokens_details = type('obj', (object,), {'cached_tokens': self.cached_tokens})()
                            else:
                                self.prompt_tokens_details = None

                    class TokenUsageResponse:
                        def __init__(self, usage_dict, model):
                            self.usage = TokenUsageMetrics(usage_dict)
                            self.model = model

                    standardized_response = TokenUsageResponse(token_usage, model_name)
                    log.info(f"📦 [TokenLoggingLLM] Created standardized response with model={model_name}, usage: prompt={standardized_response.usage.prompt_tokens}, completion={standardized_response.usage.completion_tokens}, total={standardized_response.usage.total_tokens}")

                    agent_ctx['model_name'] = model_name
                    for hook in _post_completion_hooks:
                        try:
                            log.info(f"🪝 [TokenLoggingLLM] Triggering hook: {hook.__name__}")
                            await hook(standardized_response, agent_ctx)
                        except Exception as hook_error:
                            log.error(f"❌ [TokenLoggingLLM] Hook error in {hook.__name__}: {hook_error}", exc_info=True)
                else:
                    log.warning(f"⚠️ [TokenLoggingLLM] No token usage found in result")
        except Exception as e:
            log.error(f"❌ [TokenLoggingLLM] Error triggering hooks: {e}", exc_info=True)

        return result

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override _generate to trigger token logging hooks for sync invocations."""
        result = super()._generate(messages, stop, run_manager, **kwargs)
        self._schedule_async_logging(self._fire_hooks_from_result(result))
        return result

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGeneration]:
        """Override async _astream to trigger token logging hooks after streaming completes."""
        last_usage = None
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            u = self._usage_from_chunk(chunk)
            if u:
                last_usage = u
            yield chunk

        # Fires after all chunks have been yielded successfully
        if last_usage:
            await self._fire_hooks_from_usage(
                prompt_tokens=last_usage['input_tokens'],
                completion_tokens=last_usage['output_tokens'],
                total_tokens=last_usage['total_tokens'],
            )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        """Override _stream to trigger token logging hooks after streaming completes."""
        last_usage = None
        try:
            for chunk in super()._stream(messages, stop, run_manager, **kwargs):
                u = self._usage_from_chunk(chunk)
                if u:
                    last_usage = u
                yield chunk
        finally:
            if last_usage:
                self._schedule_async_logging(
                    self._fire_hooks_from_usage(
                        prompt_tokens=last_usage['input_tokens'],
                        completion_tokens=last_usage['output_tokens'],
                        total_tokens=last_usage['total_tokens'],
                    )
                )


class TokenLoggingChatAnthropic(TokenLoggingMixin, ChatAnthropic):
    """
    Extension of ChatAnthropic that triggers token usage logging hooks across all
    invocation paths (async/sync, streaming/non-streaming).
    
    Anthropic returns usage in response_metadata with keys:
    - input_tokens
    - output_tokens
    """

    @staticmethod
    def _extract_anthropic_usage(result: ChatResult) -> Optional[Dict[str, int]]:
        """
        Extract token usage from Anthropic ChatResult.
        
        Anthropic stores usage in multiple possible locations:
        1. llm_output['usage'] - provider-specific output
        2. generation.message.usage_metadata - newer langchain format
        3. generation.message.response_metadata['usage'] - alternative location
        """
        # Method 1: Check llm_output (most common for langchain-anthropic)
        if hasattr(result, 'llm_output') and result.llm_output:
            llm_output = result.llm_output
            
            if isinstance(llm_output, dict):
                usage = llm_output.get('usage', {})
                if usage:
                    input_tokens = usage.get('input_tokens', 0) or 0
                    output_tokens = usage.get('output_tokens', 0) or 0
                    if input_tokens or output_tokens:
                        log.debug(f"[Anthropic] Token usage: input={input_tokens}, output={output_tokens}")
                        return {
                            'prompt_tokens': input_tokens,
                            'completion_tokens': output_tokens,
                            'total_tokens': input_tokens + output_tokens,
                        }
                
                token_usage = llm_output.get('token_usage', {})
                if token_usage:
                    prompt_tokens = token_usage.get('prompt_tokens', 0) or token_usage.get('input_tokens', 0) or 0
                    completion_tokens = token_usage.get('completion_tokens', 0) or token_usage.get('output_tokens', 0) or 0
                    if prompt_tokens or completion_tokens:
                        log.debug(f"[Anthropic] Token usage: prompt={prompt_tokens}, completion={completion_tokens}")
                        return {
                            'prompt_tokens': prompt_tokens,
                            'completion_tokens': completion_tokens,
                            'total_tokens': prompt_tokens + completion_tokens,
                        }
        
        # Method 2: Check generations
        if not result.generations:
            return None
            
        gen = result.generations[0]
        msg = getattr(gen, 'message', None)
        if not msg:
            return None
            
        # Try usage_metadata first (newer langchain-anthropic)
        usage_meta = getattr(msg, 'usage_metadata', None)
        if usage_meta:
            if isinstance(usage_meta, dict):
                input_tokens = usage_meta.get('input_tokens', 0) or 0
                output_tokens = usage_meta.get('output_tokens', 0) or 0
            else:
                input_tokens = getattr(usage_meta, 'input_tokens', 0) or 0
                output_tokens = getattr(usage_meta, 'output_tokens', 0) or 0
            
            if input_tokens or output_tokens:
                log.debug(f"[Anthropic] Token usage from metadata: input={input_tokens}, output={output_tokens}")
                return {
                    'prompt_tokens': input_tokens,
                    'completion_tokens': output_tokens,
                    'total_tokens': input_tokens + output_tokens,
                }
            
        # Try response_metadata (alternative location)
        resp_meta = getattr(msg, 'response_metadata', None)
        if resp_meta and isinstance(resp_meta, dict):
            usage = resp_meta.get('usage', {})
            if usage:
                input_tokens = usage.get('input_tokens', 0) or 0
                output_tokens = usage.get('output_tokens', 0) or 0
                if input_tokens or output_tokens:
                    log.debug(f"[Anthropic] Token usage from response_metadata: input={input_tokens}, output={output_tokens}")
                    return {
                        'prompt_tokens': input_tokens,
                        'completion_tokens': output_tokens,
                        'total_tokens': input_tokens + output_tokens,
                    }
        
        log.warning("[Anthropic] Could not extract token usage from response")
        return None

    @staticmethod
    def _usage_from_anthropic_chunk(chunk: ChatGeneration) -> Optional[Dict[str, int]]:
        """
        Extract token usage from an Anthropic streaming chunk.
        
        Anthropic sends usage in the final chunk's message.usage_metadata.
        """
        msg = getattr(chunk, 'message', None)
        if msg is None:
            return None
            
        # Check usage_metadata on the message
        usage_meta = getattr(msg, 'usage_metadata', None)
        if usage_meta:
            def _get(obj, key):
                return (obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)) or 0
            
            input_tokens = _get(usage_meta, 'input_tokens')
            output_tokens = _get(usage_meta, 'output_tokens')
            if input_tokens or output_tokens:
                return {
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'total_tokens': input_tokens + output_tokens,
                }
        
        # Check response_metadata as fallback
        resp_meta = getattr(msg, 'response_metadata', None)
        if resp_meta and isinstance(resp_meta, dict):
            usage = resp_meta.get('usage', {})
            if usage:
                input_tokens = usage.get('input_tokens', 0) or 0
                output_tokens = usage.get('output_tokens', 0) or 0
                if input_tokens or output_tokens:
                    return {
                        'input_tokens': input_tokens,
                        'output_tokens': output_tokens,
                        'total_tokens': input_tokens + output_tokens,
                    }
        
        return None

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override async _agenerate to trigger token logging hooks."""
        result = await super()._agenerate(messages, stop, run_manager, **kwargs)

        try:
            from src.models.azure_ai_model_service import _post_completion_hooks

            if _post_completion_hooks:
                agent_ctx = _ctx_from_session()
                token_usage = self._extract_anthropic_usage(result)
                model_name = getattr(self, 'model', None) or getattr(self, 'model_name', None)

                if token_usage:
                    class TokenUsageMetrics:
                        def __init__(self, usage_dict):
                            self.prompt_tokens = usage_dict.get('prompt_tokens', 0)
                            self.completion_tokens = usage_dict.get('completion_tokens', 0)
                            self.total_tokens = usage_dict.get('total_tokens', 0)
                            self.cached_tokens = 0
                            self.prompt_tokens_details = None

                    class TokenUsageResponse:
                        def __init__(self, usage_dict, model):
                            self.usage = TokenUsageMetrics(usage_dict)
                            self.model = model

                    standardized_response = TokenUsageResponse(token_usage, model_name)
                    log.debug(f"[Anthropic] Logging tokens: model={model_name}, total={standardized_response.usage.total_tokens}")

                    agent_ctx['model_name'] = model_name
                    for hook in _post_completion_hooks:
                        try:
                            await hook(standardized_response, agent_ctx)
                        except Exception as hook_error:
                            log.error(f"[Anthropic] Token logging hook error: {hook_error}")
                else:
                    log.debug("[Anthropic] No token usage found in response")
        except Exception as e:
            log.error(f"[Anthropic] Error in token logging: {e}")

        return result

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override _generate to trigger token logging hooks for sync invocations."""
        result = super()._generate(messages, stop, run_manager, **kwargs)
        
        token_usage = self._extract_anthropic_usage(result)
        if token_usage:
            self._schedule_async_logging(
                self._fire_hooks_from_usage(
                    prompt_tokens=token_usage['prompt_tokens'],
                    completion_tokens=token_usage['completion_tokens'],
                    total_tokens=token_usage['total_tokens'],
                )
            )
        return result

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGeneration]:
        """Override async _astream to trigger token logging hooks after streaming completes."""
        last_usage = None
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            u = self._usage_from_anthropic_chunk(chunk)
            if u:
                last_usage = u
            yield chunk

        if last_usage:
            await self._fire_hooks_from_usage(
                prompt_tokens=last_usage['input_tokens'],
                completion_tokens=last_usage['output_tokens'],
                total_tokens=last_usage['total_tokens'],
            )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        """Override _stream to trigger token logging hooks after streaming completes."""
        last_usage = None
        try:
            for chunk in super()._stream(messages, stop, run_manager, **kwargs):
                u = self._usage_from_anthropic_chunk(chunk)
                if u:
                    last_usage = u
                yield chunk
        finally:
            if last_usage:
                self._schedule_async_logging(
                    self._fire_hooks_from_usage(
                        prompt_tokens=last_usage['input_tokens'],
                        completion_tokens=last_usage['output_tokens'],
                        total_tokens=last_usage['total_tokens'],
                    )
                )
