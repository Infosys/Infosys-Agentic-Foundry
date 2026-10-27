"""shared/static_cors.py — CORS middleware that skips public static assets."""

from __future__ import annotations

from typing import Iterable

from fastapi.middleware.cors import CORSMiddleware


def _route_path(scope) -> str:
    """ASGI path with any configured ROOT_PATH sub-path prefix removed."""
    path = scope.get("path", "") or ""
    try:
        from shared.config import ROOT_PATH
    except Exception:
        ROOT_PATH = ""
    if ROOT_PATH and (path == ROOT_PATH or path.startswith(ROOT_PATH + "/")):
        return path[len(ROOT_PATH):] or "/"
    return path


class StaticExemptCORSMiddleware(CORSMiddleware):
    """``CORSMiddleware`` that passes exempt paths straight through."""

    def __init__(self, app, *, exempt_prefixes: Iterable[str] = ("/static", "/auth/refresh"), **kwargs):
        super().__init__(app, **kwargs)
        self.exempt_prefixes = tuple(exempt_prefixes)

    def is_exempt(self, scope) -> bool:
        if scope.get("type") != "http":
            return False
        path = _route_path(scope)
        return any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in self.exempt_prefixes
        )

    async def __call__(self, scope, receive, send) -> None:
        if self.is_exempt(scope):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
