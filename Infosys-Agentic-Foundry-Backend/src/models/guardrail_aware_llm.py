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
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

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
      5: tool_id  6: tool_name   7: model_used    ...
    """
    try:
        from telemetry_wrapper import SessionContext
        ctx = SessionContext.get()
        def _v(val):
            return val if val != 'Unassigned' else None
        return {
            'user_id':    _v(ctx[0]),
            'session_id': _v(ctx[1]),
            'agent_id':   _v(ctx[3]),
            'agent_name': _v(ctx[4]),
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
        """
        Inject agent/session identifiers as extra HTTP headers so downstream
        proxies (LiteLLM) can attribute the call. Uses SessionContext — no
        dependency on the missing get_agent_context helper.
        """
        try:
            ctx = _ctx_from_session()
            agent_id = ctx.get('agent_id')
            if agent_id:
                extra_headers = kwargs.get('extra_headers', {})
                extra_headers['x-agent-id'] = agent_id
                if ctx.get('agent_name'):
                    extra_headers['x-agent-name'] = ctx['agent_name']
                if ctx.get('session_id'):
                    extra_headers['x-session-id'] = ctx['session_id']
                if ctx.get('user_id'):
                    extra_headers['x-user-id'] = ctx['user_id']
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
        """Override async _agenerate to handle guardrail errors, inject agent context, and log tokens."""
        kwargs = self._inject_session_headers(kwargs)

        try:
            result = await super()._agenerate(messages, stop, run_manager, **kwargs)

            # Trigger post-completion hooks for token logging
            log.info(f"🔍 [GuardrailLLM] Result type: {type(result)}")
            log.info(f"🔍 [GuardrailLLM] Result attributes: {dir(result)}")
            if hasattr(result, 'llm_output'):
                log.info(f"🔍 [GuardrailLLM] LLM output: {result.llm_output}")
            if hasattr(result, 'generations') and result.generations:
                gen = result.generations[0]
                log.info(f"🔍 [GuardrailLLM] Generation type: {type(gen)}")
                log.info(f"🔍 [GuardrailLLM] Generation attributes: {dir(gen)}")
                if hasattr(gen, 'message'):
                    log.info(f"🔍 [GuardrailLLM] Message: {gen.message}")
                    if hasattr(gen.message, 'response_metadata'):
                        log.info(f"🔍 [GuardrailLLM] Response metadata: {gen.message.response_metadata}")

            from src.models.azure_ai_model_service import _post_completion_hooks
            if _post_completion_hooks:
                log.info(f"🪝 [GuardrailLLM] Found {len(_post_completion_hooks)} hooks to trigger")
                token_usage = None

                if hasattr(result, 'llm_output') and result.llm_output:
                    token_usage = result.llm_output.get('token_usage', None)
                    log.info(f"📊 [GuardrailLLM] Token usage from llm_output: {token_usage}")
                    log.info(f"📊 [GuardrailLLM] Complete llm_output keys: {list(result.llm_output.keys())}")
                    log.info(f"📊 [GuardrailLLM] Complete llm_output: {result.llm_output}")

                if token_usage:
                    class TokenUsageMetrics:
                        def __init__(self, usage_dict):
                            self.prompt_tokens = usage_dict.get('prompt_tokens', 0)
                            self.completion_tokens = usage_dict.get('completion_tokens', 0)
                            self.total_tokens = usage_dict.get('total_tokens', 0)
                            prompt_details = usage_dict.get('prompt_tokens_details', {})
                            self.cached_tokens = prompt_details.get('cached_tokens', 0) if prompt_details else 0
                            self.prompt_tokens_details = type('obj', (object,), {'cached_tokens': self.cached_tokens})() if prompt_details else None

                    class TokenUsageResponse:
                        def __init__(self, usage_dict):
                            self.usage = TokenUsageMetrics(usage_dict)

                    standardized_response = TokenUsageResponse(token_usage)
                    log.info(f"📦 [GuardrailLLM] Created standardized response with usage: prompt={standardized_response.usage.prompt_tokens}, completion={standardized_response.usage.completion_tokens}, total={standardized_response.usage.total_tokens}")

                    # Build hook context from SessionContext (replaces missing get_agent_context)
                    hook_ctx = _ctx_from_session()

                    model_name = None
                    if result.llm_output:
                        model_name = result.llm_output.get('model_name', None)
                        log.info(f"🔍 [GuardrailLLM] Model from llm_output: {model_name}")

                    if not model_name:
                        model_name = getattr(self, 'deployment_name', None) or getattr(self, 'model', None)
                        log.info(f"🔍 [GuardrailLLM] Model from self attributes: deployment_name={getattr(self, 'deployment_name', None)}, model={getattr(self, 'model', None)}")

                    hook_ctx['model_name'] = model_name
                    log.info(f"🔧 [GuardrailLLM] Final model name for tracking: {model_name}")

                    for hook in _post_completion_hooks:
                        try:
                            log.info(f"🪝 [GuardrailLLM] Triggering hook: {hook.__name__}")
                            await hook(standardized_response, hook_ctx)
                        except Exception as hook_error:
                            log.error(f"❌ [GuardrailLLM] Hook error in {hook.__name__}: {hook_error}", exc_info=True)
                else:
                    log.warning(f"⚠️ [GuardrailLLM] No token usage found in result")

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
        """Override async _astream to handle guardrail errors, inject agent context, and log tokens."""
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

        # Fires only on successful stream completion (not on exception)
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
        """Override async _agenerate to handle guardrail errors, inject agent context, and log tokens."""
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
        """Override async _astream to handle guardrail errors, inject agent context, and log tokens."""
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

        # Fires only on successful stream completion (not on exception)
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
        """Override async _agenerate to trigger token logging hooks."""
        result = await super()._agenerate(messages, stop, run_manager, **kwargs)

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
