from __future__ import annotations

import enum
import inspect
from collections.abc import Callable
from dataclasses import KW_ONLY, dataclass
from typing import Any

from typing_extensions import type_repr

from ._types import NOT_SET, Scope


class ProviderKind(enum.IntEnum):
    CLASS = 1
    FUNCTION = 2
    COROUTINE = 3
    GENERATOR = 4
    ASYNC_GENERATOR = 5

    @classmethod
    def from_call(cls, call: Callable[..., Any]) -> ProviderKind:
        if inspect.isclass(call):
            return cls.CLASS
        if inspect.iscoroutinefunction(call):
            return cls.COROUTINE
        if inspect.isasyncgenfunction(call):
            return cls.ASYNC_GENERATOR
        if inspect.isgeneratorfunction(call):
            return cls.GENERATOR
        if inspect.isfunction(call) or inspect.ismethod(call):
            return cls.FUNCTION
        raise TypeError(
            f"The provider `{call}` is invalid because it is not a callable object."
        )


@dataclass(frozen=True, slots=True)
class ProviderParameter:
    dependency_type: Any
    name: str
    default: Any
    has_default: bool
    provider: Provider | None = None
    shared_scope: bool = False


@dataclass(frozen=True, slots=True)
class Provider:
    dependency_type: Any
    factory: Callable[..., Any]
    scope: Scope
    from_context: bool
    parameters: tuple[ProviderParameter, ...]
    is_class: bool
    is_coroutine: bool
    is_generator: bool
    is_async_generator: bool
    is_async: bool
    is_resource: bool

    def __repr__(self) -> str:
        dep_repr = type_repr(self.dependency_type)
        # For class providers, factory == dependency_type, so just show the type
        if self.is_class:
            return dep_repr
        # For factory providers, include the factory path
        factory_repr = type_repr(self.factory)
        return f"{dep_repr} (via {factory_repr})"


@dataclass(slots=True)
class ProviderDef:
    dependency_type: Any = NOT_SET
    factory: Callable[..., Any] = NOT_SET
    _: KW_ONLY
    from_context: bool = False
    scope: Scope = "singleton"
    alias: Any = NOT_SET
