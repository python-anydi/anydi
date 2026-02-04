"""AnyDI FastStream extension."""

from __future__ import annotations

import inspect
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

from fast_depends.dependencies import Dependant
from faststream import BaseMiddleware, ContextRepo, StreamMessage

from anydi import Container
from anydi._marker import Inject, Marker, extend_marker

if TYPE_CHECKING:
    from faststream._internal.basic_types import AsyncFuncAny
    from faststream._internal.broker import BrokerUsecase
    from faststream._internal.types import AnyMsg

__all__ = [
    "Inject",
    "RequestScopedMiddleware",
    "get_container",
    "get_container_from_context",
    "install",
]


def get_container(broker: BrokerUsecase[Any, Any]) -> Container:
    """Get the AnyDI container from a FastStream broker."""
    return cast(Container, getattr(broker, "_container"))


def get_container_from_context(context: ContextRepo) -> Container:
    return get_container(context.broker)


class RequestScopedMiddleware(BaseMiddleware):
    @cached_property
    def container(self) -> Container:
        return get_container_from_context(self.context)

    async def consume_scope(
        self, call_next: AsyncFuncAny, msg: StreamMessage[AnyMsg]
    ) -> Any:
        async with self.container.arequest_context():
            return await call_next(msg)


class FastStreamMarker(Dependant, Marker):
    def __init__(self) -> None:
        Marker.__init__(self)
        self._current_owner = "faststream"
        Dependant.__init__(
            self,
            self._faststream_dependency,
            use_cache=True,
            cast=True,
            cast_result=True,
        )
        self._current_owner = None

    async def _faststream_dependency(self, context: ContextRepo) -> Any:
        container = get_container_from_context(context)
        return await container.aresolve(self.dependency_type)


# Configure Inject() and Provide[T] to use FastStream-specific marker
extend_marker(FastStreamMarker)


def _get_broker_handlers(broker: BrokerUsecase[Any, Any]) -> list[Any]:
    return [subscriber.calls[0].handler for subscriber in broker.subscribers]


def install(broker: BrokerUsecase[Any, Any], container: Container) -> None:
    """Install AnyDI into a FastStream broker."""
    broker._container = container  # type: ignore
    for handler in _get_broker_handlers(broker):
        call = handler._original_call
        for parameter in inspect.signature(call, eval_str=True).parameters.values():
            _, should_inject, marker = container.validate_injected_parameter(
                parameter, call=call
            )
            if should_inject and marker:
                marker.set_owner("faststream")
