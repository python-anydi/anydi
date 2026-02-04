"""AnyDI FastAPI extension."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, params
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.requests import HTTPConnection

from anydi import Container, Inject
from anydi._marker import Marker, extend_marker

from .starlette.middleware import RequestScopedMiddleware

__all__ = ["Inject", "RequestScopedMiddleware", "get_container", "install"]


def get_container(connection: HTTPConnection) -> Container:
    return cast(Container, connection.app.state.container)


class FastAPIMarker(params.Depends, Marker):
    def __init__(self) -> None:
        Marker.__init__(self)
        self._current_owner = "fastapi"
        params.Depends.__init__(
            self, dependency=self._fastapi_dependency, use_cache=True
        )
        self._current_owner = None

    async def _fastapi_dependency(
        self, container: Annotated[Container, Depends(get_container)]
    ) -> Any:
        return await container.aresolve(self.dependency_type)


# Configure Inject() and Provide[T] to use FastAPI-specific marker at import time
# This is also called in install() to ensure it's set correctly even if other
# extensions have overwritten it
extend_marker(FastAPIMarker)


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

    # Validate routes (both HTTP and WebSocket)
    patched: set[tuple[Any, ...]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute | APIWebSocketRoute):
            continue
        _validate_route_dependencies(route, container, patched)
