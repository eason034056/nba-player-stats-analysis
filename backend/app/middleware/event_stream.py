"""Set Cache-Control on any text/event-stream response.

There is no SSE route today. This middleware applies the header when one
is added, without buffering the body.
"""

from starlette.datastructures import MutableHeaders


class EventStreamCacheControlMiddleware:
    """Add `Cache-Control: no-cache, no-transform` to event-stream responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_cache_control(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                content_type = headers.get("content-type", "")
                if content_type.startswith("text/event-stream"):
                    headers["cache-control"] = "no-cache, no-transform"
            await send(message)

        await self.app(scope, receive, send_with_cache_control)
