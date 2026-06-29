"""AnyDI FastAPI extension."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Iterator
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, params, routing as fastapi_routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.requests import HTTPConnection

from anydi import Container, Inject
from anydi._marker import Marker, extend_marker

from .starlette.middleware import RequestScopedMiddleware

__all__ = ["Inject", "RequestScopedMiddleware", "get_container", "install"]

# FastAPI >= 0.138 wraps `include_router` routes in an `_IncludedRouter` instead
# of flattening them into `app.routes`.
_IncludedRouter: Any = getattr(fastapi_routing, "_IncludedRouter", None)


def get_container(connection: HTTPConnection) -> Container:
    return cast(Container, connection.app.state.container)


class FastAPIMarker(Marker, params.Depends):
    def __init__(self) -> None:
        Marker.__init__(self)
        self._current_owner = "fastapi"
        # Set the framework fields directly instead of calling the (now frozen)
        # params.Depends.__init__; the Marker descriptors route them per-owner.
        self.dependency = self._fastapi_dependency
        self.use_cache = True
        self.scope = None
        self._current_owner = None

    async def _fastapi_dependency(
        self, container: Annotated[Container, Depends(get_container)]
    ) -> Any:
        return await container.aresolve(self.dependency_type)


# Configure Inject() and Provide[T] to use FastAPI-specific marker at import time
# This is also called in install() to ensure it's set correctly even if other
# extensions have overwritten it
extend_marker(FastAPIMarker)


def _iter_routes(
    routes: Iterable[Any],
) -> Iterator[APIRoute | APIWebSocketRoute]:
    """Yield all API routes, descending into routers added via include_router."""
    for route in routes:
        if isinstance(route, APIRoute | APIWebSocketRoute):
            yield route
        elif _IncludedRouter is not None and isinstance(route, _IncludedRouter):
            yield from _iter_routes(route.original_router.routes)


def _iter_dependencies(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    if dependant.dependencies:
        for sub_dependant in dependant.dependencies:
            yield from _iter_dependencies(sub_dependant)


def _validate_route_dependencies(
    route: APIRoute | APIWebSocketRoute,
    container: Container,
    patched: set[tuple[Any, ...]],
) -> None:
    for dependant in _iter_dependencies(route.dependant):
        if dependant.cache_key in patched:
            continue
        patched.add(dependant.cache_key)
        call, *_ = dependant.cache_key
        if not call:
            continue  # pragma: no cover
        for parameter in inspect.signature(call, eval_str=True).parameters.values():
            _, should_inject, marker = container.validate_injected_parameter(
                parameter, call=call
            )
            if should_inject and marker:
                marker.set_owner("fastapi")


def install(app: FastAPI, container: Container) -> None:
    """Install AnyDI into a FastAPI application."""
    app.state.container = container

    # Register websocket scope with request as parent if not already registered
    if not container.has_scope("websocket"):
        container.register_scope("websocket", parents=["request"])

    # Validate routes (both HTTP and WebSocket), including routes registered
    # through include_router.
    patched: set[tuple[Any, ...]] = set()
    for route in _iter_routes(app.routes):
        _validate_route_dependencies(route, container, patched)
