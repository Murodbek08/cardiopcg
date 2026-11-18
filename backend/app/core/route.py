"""APIRoute that commits the request transaction *before* the response is returned to the client."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from app.services import realtime


class TxRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            response = await original(request)
            db = getattr(request.state, "db", None)
            if db is not None and response.status_code < 400:
                await db.commit()
                await realtime.flush_events(db)
            return response

        return handler
