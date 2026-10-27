"""
ChatVertexAIRaw — LangChain BaseChatModel for Google Vertex AI Gemini.

Built using only Python stdlib + PyJWT (no google-* libraries required).
Designed for environments where:
  - pip / PyPI is blocked (cannot install langchain-google-vertexai)
  - Corporate SSL inspection breaks standard cert validation (Zscaler etc.)
  - gcloud CLI cannot be installed

Uses service-account JSON for auth and a custom SSL context that adds the
corporate CA bundle and relaxes the strict-X.509 check (the corporate cert's
Basic Constraints are not marked critical).

Phase 1: synchronous, non-streaming, no tool calling.
Phase 2 (later): _stream() via streamGenerateContent SSE.
Phase 3 (later): tool calling via Vertex's FunctionDeclaration schema.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Base64 data-URL images are huge (~1-2 MB); strip them from history (Vertex 32k input-token limit).
_DATA_URL_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+\)"
)


def _strip_image_data_urls(text: str) -> str:
    """Replace Markdown data-URL image tags with a short placeholder.

    Preserves alt text so the LLM still has context that an image was sent
    previously, without re-uploading megabytes of base64.

    `![sunset photo](data:image/png;base64,iVBORw0K...)` → `[image: sunset photo]`
    """
    return _DATA_URL_IMAGE_RE.sub(
        lambda m: f"[image: {m.group(1) or 'previously generated'}]",
        text,
    )


_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _autodetect_image_dir() -> Optional[Path]:
    """Walk up from this file looking for IAF-Agent-Studio/static/.

    Returns IAF-Agent-Studio/static/generated_images if found, else None.
    """
    p = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = p / "IAF-Agent-Studio" / "static"
        if candidate.exists():
            return candidate / "generated_images"
        if p.parent == p:
            break
        p = p.parent
    return None


def _cleanup_old_images(directory: Path, retention_days: int = 7) -> int:
    """Delete files older than retention_days. Returns number deleted.

    Fail-silent — never raises. Called lazily on every image save so the
    directory can't grow unbounded. Trivial overhead since it only stats
    files in the directory (no recursion).
    """
    if retention_days <= 0:
        return 0
    cutoff = time.time() - (retention_days * 86400)
    deleted = 0
    try:
        for f in directory.iterdir():
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except OSError:
                continue
    except OSError:
        pass
    return deleted


def _save_image_bytes(
    b64_data: str,
    mime_type: str,
    output_dir: Path,
    url_prefix: str,
) -> Optional[str]:
    """Decode base64 + write to disk + return the URL path.

    Returns None on failure (caller should fall back to inline data URL).
    """
    try:
        ext = _MIME_TO_EXT.get(mime_type.lower(), ".bin")
        filename = f"{uuid.uuid4().hex}{ext}"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / filename
        # Vertex returns base64 sometimes with whitespace — strip it
        clean_b64 = re.sub(r"\s+", "", b64_data)
        target.write_bytes(base64.b64decode(clean_b64))
        _cleanup_old_images(output_dir)
        # URL prefix should end with '/' for clean join
        return url_prefix.rstrip("/") + "/" + filename
    except Exception as e:
        logger.warning("vertex_chat: failed to save image to disk: %r — falling back to inline data URL", e)
        return None

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field, PrivateAttr


class ChatVertexAIRaw(BaseChatModel):
    """Vertex AI Gemini chat model using stdlib HTTP.

    Required config (all via constructor or env in ModelRegistry):
      project          — GCP project id (e.g. 'iaf-madhan')
      location         — region (default 'us-central1')
      model            — model name (e.g. 'gemini-2.5-flash')
      sa_key_path      — absolute path to service-account JSON
      ca_bundle_path   — optional PEM bundle for SSL trust (combined certifi
                         + system roots so corporate CAs are recognised)
      temperature      — default 0.7
    """

    project: str
    location: str = "us-central1"
    model: str = "gemini-2.5-flash"
    sa_key_path: str
    ca_bundle_path: Optional[str] = None
    temperature: float = 0.7
    # Image output dir; if None, images are inlined as base64.
    image_output_dir: Optional[str] = None
    # URL prefix that maps the output_dir to a browser-accessible path
    # (e.g. "/static/generated_images") — must align with the static handler.
    image_url_prefix: str = "/static/generated_images"
    # Days to keep generated images before lazy cleanup deletes them. <=0 disables.
    image_retention_days: int = 7
    # Optional Gemini thinking capture. Off by default for legacy parity.
    thinking_enabled: bool = False
    thinking_budget: Optional[int] = None

    # Private cached state — not part of the public model config
    _ssl_context: Optional[ssl.SSLContext] = PrivateAttr(default=None)
    _sa_payload: Optional[dict] = PrivateAttr(default=None)
    _access_token: Optional[str] = PrivateAttr(default=None)
    _token_expires_at: int = PrivateAttr(default=0)


    def _get_ssl_context(self) -> ssl.SSLContext:
        if self._ssl_context is not None:
            return self._ssl_context
        ctx = ssl.create_default_context(cafile=self.ca_bundle_path)
        # Relax Basic Constraints criticality for corporate CAs (3.11+ is strict); chain and hostname checks stay on.
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        self._ssl_context = ctx
        return ctx


    def _load_sa(self) -> dict:
        if self._sa_payload is None:
            p = Path(self.sa_key_path)
            if not p.exists():
                raise FileNotFoundError(f"Service account key not found: {self.sa_key_path}")
            sa = json.loads(p.read_text())
            if sa.get("type") != "service_account":
                raise ValueError(f"{self.sa_key_path} is not a service_account key")
            self._sa_payload = sa
        return self._sa_payload

    def _get_access_token(self) -> str:
        now = int(time.time())
        # Refresh 60s before actual expiry to avoid edge-case races
        if self._access_token and self._token_expires_at - 60 > now:
            return self._access_token

        try:
            import jwt as pyjwt
        except ImportError as e:
            raise ImportError(
                "PyJWT is required for ChatVertexAIRaw. "
                "Install via: pip install PyJWT  (cryptography must also be available)"
            ) from e

        sa = self._load_sa()
        token_uri = sa.get("token_uri", "https://oauth2.googleapis.com/token")
        signed = pyjwt.encode(
            {
                "iss": sa["client_email"],
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "aud": token_uri,
                "iat": now,
                "exp": now + 3600,
            },
            sa["private_key"],
            algorithm="RS256",
        )

        req = urllib.request.Request(
            token_uri,
            data=urllib.parse.urlencode(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed,
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=self._get_ssl_context(), timeout=20) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"OAuth token exchange failed: HTTP {e.code} — {e.read().decode()[:300]}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Network error contacting {token_uri}: {e!r}") from e

        token = payload.get("access_token")
        if not token:
            raise RuntimeError(f"Token response had no access_token: {payload}")
        self._access_token = token
        self._token_expires_at = now + int(payload.get("expires_in", 3600))
        return token


    @staticmethod
    def _to_vertex_function_declarations(tools: List[Any]) -> List[dict]:
        """Convert LangChain tools → Vertex AI functionDeclarations format.

        Reuses LangChain's OpenAI converter (which produces JSON Schema for
        parameters) and reshapes to Vertex's nesting:
          OpenAI:  {type: "function", function: {name, description, parameters}}
          Vertex:  {name, description, parameters}  (inside functionDeclarations[])
        """
        decls: List[dict] = []
        for t in tools:
            oa = convert_to_openai_tool(t)  # {"type": "function", "function": {...}}
            fn = oa.get("function", oa)
            decl = {"name": fn["name"], "description": fn.get("description", "")}
            params = fn.get("parameters")
            if params:
                # Vertex rejects unknown JSON Schema keys; strip $defs/title/etc.
                decl["parameters"] = _sanitise_schema_for_vertex(params)
            decls.append(decl)
        return decls


    @staticmethod
    def _messages_to_vertex(msgs: List[BaseMessage]) -> dict:
        """Convert LangChain messages → Vertex AI request body shape."""
        system_text: Optional[str] = None
        contents: list[dict] = []
        for m in msgs:
            if isinstance(m, SystemMessage):
                # Vertex has a dedicated systemInstruction field — concat if multiple
                system_text = (
                    str(m.content) if system_text is None
                    else f"{system_text}\n\n{m.content}"
                )
            elif isinstance(m, HumanMessage):
                contents.append({"role": "user", "parts": [{"text": str(m.content)}]})
            elif isinstance(m, AIMessage):
                # AIMessage may carry tool_calls — Vertex expects functionCall parts
                parts: list[dict] = []
                if m.content:
                    # Strip embedded data-URL images — they balloon prompt size and
                    # blow past 32k input tokens. Keep alt text as a placeholder.
                    text_content = _strip_image_data_urls(str(m.content))
                    parts.append({"text": text_content})
                for tc in (getattr(m, "tool_calls", None) or []):
                    parts.append({
                        "functionCall": {
                            "name": tc.get("name", ""),
                            "args": tc.get("args", {}),
                        }
                    })
                if not parts:
                    parts = [{"text": ""}]
                contents.append({"role": "model", "parts": parts})
            elif isinstance(m, ToolMessage):
                # Vertex expects functionResponse parts under role=user
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": getattr(m, "name", "") or "",
                            "response": {"result": str(m.content)},
                        }
                    }],
                })
            else:
                contents.append({"role": "user", "parts": [{"text": str(m.content)}]})

        body: dict = {"contents": contents}
        if system_text:
            body["systemInstruction"] = {"role": "user", "parts": [{"text": system_text}]}
        return body


    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        token = self._get_access_token()
        body = self._messages_to_vertex(messages)
        body["generationConfig"] = {"temperature": self.temperature}
        if self.thinking_enabled:
            thinking_config: dict[str, Any] = {"includeThoughts": True}
            if self.thinking_budget is not None:
                thinking_config["thinkingBudget"] = int(self.thinking_budget)
            body["generationConfig"]["thinkingConfig"] = thinking_config
        if stop:
            body["generationConfig"]["stopSequences"] = list(stop)

        # If the model supports image output (name contains "-image"), tell Vertex
        # to return BOTH text and image modalities. Required for gemini-2.5-flash-image.
        image_modality_active = "-image" in self.model.lower()
        if image_modality_active:
            body["generationConfig"]["responseModalities"] = ["TEXT", "IMAGE"]
            # Image-capable Gemini rejects tool declarations; suppress tool calls invented as text.
            suppress_text = (
                "\n\n[IMAGE-MODE INSTRUCTIONS — OVERRIDES ANY EARLIER GUIDANCE]\n"
                "You are generating an image response. STRICTLY:\n"
                "1. Generate the image directly. Do not describe the steps you would take.\n"
                "2. Do NOT output any tool calls or shell commands as text. The following are FORBIDDEN in your response:\n"
                "   shell(...), cat(...), python3(...), run_shell(...), invoke_skill(...), invoke_plan(...), create_plan(...), write_file(...)\n"
                "3. Do NOT say 'first I will consult / read / look up / fetch'. The context you need is ALREADY in your system prompt.\n"
                "4. Reply with ONLY: the image, then a 3-5 sentence design rationale, then optional follow-up offer.\n"
            )
            si = body.get("systemInstruction")
            if si is None:
                body["systemInstruction"] = {
                    "role": "user",
                    "parts": [{"text": suppress_text.strip()}],
                }
            else:
                # Append to existing system instruction
                existing_parts = si.get("parts") or []
                existing_parts.append({"text": suppress_text})
                si["parts"] = existing_parts

        # Image modality rejects custom functionDeclarations, so skip tool binding when it is active.
        raw_tools = kwargs.get("tools")
        if raw_tools and not image_modality_active:
            decls = self._to_vertex_function_declarations(raw_tools)
            if decls:
                body["tools"] = [{"functionDeclarations": decls}]
            tool_choice = kwargs.get("tool_choice")
            if tool_choice in ("any", "required"):
                body["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
            elif tool_choice == "none":
                body["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}

        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1"
            f"/projects/{self.project}/locations/{self.location}"
            f"/publishers/google/models/{self.model}:generateContent"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=self._get_ssl_context(), timeout=120) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"Vertex AI HTTP {e.code} on model={self.model}: {e.read().decode()[:400]}"
            ) from e

        # Parse candidate parts: may contain text, functionCall, or inlineData (image)
        text_parts: list[str] = []
        image_markdown: list[str] = []
        tool_calls: list[dict] = []
        reasoning_items: list[dict] = []
        image_count = 0
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Vertex AI response shape: {data}") from e

        for idx, part in enumerate(parts):
            if "text" in part:
                if part.get("thought"):
                    reasoning_items.append({
                        "type": "thinking",
                        "text": str(part.get("text") or ""),
                    })
                else:
                    text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{idx}",
                    "name": fc.get("name", ""),
                    "args": fc.get("args", {}),
                    "type": "tool_call",
                })
            elif "inlineData" in part:
                # Image (or other binary) response — Gemini image-capable models
                # return parts like: {"inlineData": {"mimeType": "image/png", "data": "<base64>"}}
                inline = part["inlineData"]
                mime = inline.get("mimeType", "image/png")
                b64  = inline.get("data", "")
                if b64:
                    image_count += 1
                    saved_url: Optional[str] = None
                    # Prefer file-backed storage — keeps conversation history small
                    # and avoids 588K-token prompt bloat on follow-up turns.
                    if self.image_output_dir:
                        saved_url = _save_image_bytes(
                            b64_data=b64,
                            mime_type=mime,
                            output_dir=Path(self.image_output_dir),
                            url_prefix=self.image_url_prefix,
                        )
                    if saved_url:
                        image_markdown.append(
                            f"![generated image {image_count}]({saved_url})"
                        )
                    else:
                        # Fallback: inline base64 (legacy behaviour, history-bloating)
                        image_markdown.append(
                            f"![generated image {image_count}](data:{mime};base64,{b64})"
                        )

        usage = data.get("usageMetadata", {})
        finish = data["candidates"][0].get("finishReason", "STOP")

        # Assemble: text first, then images (each on its own line)
        chunks = ["".join(text_parts).rstrip()] if text_parts else []
        chunks.extend(image_markdown)
        content = "\n\n".join(c for c in chunks if c)

        msg = AIMessage(
            content=content,
            tool_calls=tool_calls,
            additional_kwargs={
                "provider": "vertex",
                "reasoning_items": reasoning_items,
            },
            response_metadata={
                "model": self.model,
                "finish_reason": finish,
                "token_usage": usage,
                "image_count": image_count,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(
        self,
        tools: List[Any],
        *,
        tool_choice: Optional[Any] = None,
        **kwargs: Any,
    ) -> Runnable:
        """Bind tools to this model — forwards raw tools through .bind().

        `_generate` reads them from kwargs and converts to Vertex's
        functionDeclarations format at call time.
        """
        bind_kwargs: dict[str, Any] = {"tools": list(tools)}
        if tool_choice is not None:
            bind_kwargs["tool_choice"] = tool_choice
        return self.bind(**bind_kwargs, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "vertex-raw"

    @property
    def _identifying_params(self) -> dict:
        return {
            "model": self.model,
            "project": self.project,
            "location": self.location,
        }



def _sanitise_schema_for_vertex(schema: dict) -> dict:
    """Strip JSON Schema fields that Vertex's OpenAPI subset rejects.

    Vertex accepts a subset of OpenAPI Schema. Unknown fields like `$defs`,
    `$ref`, `additionalProperties`, `title`, `definitions` cause 400 errors.
    """
    if not isinstance(schema, dict):
        return schema
    DROP = {"$defs", "$ref", "$schema", "definitions", "additionalProperties", "title"}
    out: dict = {}
    for k, v in schema.items():
        if k in DROP:
            continue
        if isinstance(v, dict):
            out[k] = _sanitise_schema_for_vertex(v)
        elif isinstance(v, list):
            out[k] = [_sanitise_schema_for_vertex(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out
