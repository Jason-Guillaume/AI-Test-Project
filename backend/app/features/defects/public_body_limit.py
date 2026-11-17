"""Limit public share write bodies before FastAPI parses them."""

from starlette.responses import JSONResponse


class PublicShareBodyLimit:
    def __init__(self, app, limit: int = 16384):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}
                or not scope["path"].startswith("/api/v1/public/defect-shares/")):
            await self.app(scope, receive, send)
            return
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                response = JSONResponse({"detail": "请求体过大"}, status_code=413, headers={
                    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                    "X-Robots-Tag": "noindex, nofollow",
                    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                })
                await response(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
