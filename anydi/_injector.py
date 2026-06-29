"""Dependency injection utilities."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    TypeVar,
    cast,
    get_args,
    get_origin,
)

from typing_extensions import ParamSpec, type_repr

from ._marker import Marker, is_marker

if TYPE_CHECKING:
    from ._container import Container

T = TypeVar("T", bound=Any)
P = ParamSpec("P")


class Injector:
    """Handles dependency injection for callables."""

    def __init__(self, container: Container) -> None:
        self.container = container
        self._cache: dict[Callable[..., Any], Callable[..., Any]] = {}

    def inject(self, call: Callable[P, T]) -> Callable[P, T]:
        """Inject dependencies into a callable."""
        if call in self._cache:
            return cast(Callable[P, T], self._cache[call])

        injected_params = self._get_injected_params(call)
        if not injected_params:
            self._cache[call] = call
            return call

        if inspect.iscoroutinefunction(call):

            @functools.wraps(call)
            async def awrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                for name, annotation in injected_params.items():
                    kwargs[name] = await self.container.aresolve(annotation)
                return cast(T, await call(*args, **kwargs))

            self._cache[call] = awrapper

            return awrapper  # type: ignore

        @functools.wraps(call)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            for name, annotation in injected_params.items():
                kwargs[name] = self.container.resolve(annotation)
            return call(*args, **kwargs)

        self._cache[call] = wrapper

        return wrapper

    def _get_injected_params(self, call: Callable[..., Any]) -> dict[str, Any]:
        """Get the injected parameters of a callable object."""
        injected_params: dict[str, Any] = {}
        for parameter in inspect.signature(call, eval_str=True).parameters.values():
            dependency_type, should_inject, _ = self.validate_parameter(
                parameter, call=call
            )
            if should_inject:
                injected_params[parameter.name] = dependency_type
        return injected_params

    def validate_parameter(
        self, parameter: inspect.Parameter, *, call: Callable[..., Any]
    ) -> tuple[Any, bool, Marker | None]:
        """Validate an injected parameter."""
        parameter = self.unwrap_parameter(parameter)
        dependency_type = parameter.annotation

        marker = parameter.default
        if not is_marker(marker):
            return dependency_type, False, None

        if dependency_type is inspect.Parameter.empty:
            raise TypeError(
                f"Missing `{type_repr(call)}` parameter `{parameter.name}` annotation."
            )

        # Set inject marker dependency type
        parameter.default.dependency_type = dependency_type

        if not self.container.has_provider_for(dependency_type):
            raise LookupError(
                f"`{type_repr(call)}` has an unknown dependency parameter "
                f"`{parameter.name}` with an annotation of "
                f"`{type_repr(dependency_type)}`."
            )

        return dependency_type, True, marker

    @staticmethod
    def unwrap_parameter(parameter: inspect.Parameter) -> inspect.Parameter:
        if get_origin(parameter.annotation) is not Annotated:
            return parameter

        origin, *metadata = get_args(parameter.annotation)

        if not metadata or not is_marker(metadata[-1]):
            return parameter

        if is_marker(parameter.default):
            raise TypeError(
                "Cannot specify `Inject` in `Annotated` and "
                f"default value together for '{parameter.name}'"
            )

        if parameter.default is not inspect.Parameter.empty:
            return parameter

        marker = metadata[-1]
        new_metadata = metadata[:-1]
        if new_metadata:
            if hasattr(Annotated, "__getitem__"):
                new_annotation = Annotated.__getitem__((origin, *new_metadata))
            else:
                new_annotation = Annotated.__class_getitem__((origin, *new_metadata))
        else:
            new_annotation = origin
        return parameter.replace(annotation=new_annotation, default=marker)
