# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from fastapi.middleware.gzip import GZipMiddleware


class CustomGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope, receive, send):
        if (not scope.get("path", "").startswith("/chat")) and (not scope.get("path", "").startswith("/evaluation")):
            return await super().__call__(scope, receive, send)
        await self.app(scope, receive, send)
