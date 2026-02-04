"""Shared AnyDI utils module."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Iterator
from types import NoneType
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin

from typing_extensions import Sentinel

Scope = Literal["transient", "singleton", "request"] | str

NOT_SET = Sentinel("NOT_SET")


class Event:
    """Represents an event object."""

    __slots__ = ()


def is_event_type(obj: Any) -> bool:
    """Checks if an object is an event type."""
    return inspect.isclass(obj) and issubclass(obj, Event)


def is_context_manager(obj: Any) -> bool:
    """Check if the given object is a context manager."""
    return hasattr(obj, "__enter__") and hasattr(obj, "__exit__")


def is_async_context_manager(obj: Any) -> bool:
    """Check if the given object is an async context manager."""
    return hasattr(obj, "__aenter__") and hasattr(obj, "__aexit__")


def is_none_type(tp: Any) -> bool:
    """Check if the given object is a None type."""
    return tp in (None, NoneType)


def is_iterator_type(tp: Any) -> bool:
    """Check if the given object is an iterator type."""
    return tp in (Iterator, AsyncIterator)


def to_list(value: Any) -> list[Any]:
    """Convert a value to a list, handling None and sequences."""
    if value is None or value is NOT_SET:
        return []
    if isinstance(value, list | tuple):
        return list(value)  # type: ignore[arg-type]
    return [value]


# Generic TypeVar utilities


def build_typevar_map(
    cls: type[Any], typevar_map: dict[TypeVar, type[Any]] | None = None
) -> dict[TypeVar, type[Any]]:
    """Build a mapping from TypeVars to concrete types for a class."""
    if typevar_map is None:
        typevar_map = {}

    orig_bases = getattr(cls, "__orig_bases__", ())

    for base in orig_bases:
        origin = get_origin(base)
        if origin is None:
            # Not a parameterized generic, check if it's a class with bases
            if isinstance(base, type):
                typevar_map = build_typevar_map(base, typevar_map)
            continue

        args = get_args(base)
        if not args:
            continue

        # Get TypeVar parameters from the origin class
        type_params = getattr(origin, "__parameters__", ())
        if not type_params:
            # Try __type_params__ for Python 3.12+ style generics
            type_params = getattr(origin, "__type_params__", ())

        # Map each TypeVar to its corresponding argument
        typevar_map = _map_typevars_to_args(type_params, args, typevar_map)

        # Recursively process the origin class
        if isinstance(origin, type):
            typevar_map = build_typevar_map(origin, typevar_map)
    return typevar_map


def _map_typevars_to_args(
    type_params: tuple[Any, ...],
    args: tuple[Any, ...],
    typevar_map: dict[TypeVar, type[Any]],
) -> dict[TypeVar, type[Any]]:
    """Map TypeVar parameters to their corresponding type arguments."""
    new_map = typevar_map.copy()
    for i, type_param in enumerate(type_params):
        if i >= len(args):
            break
        if not isinstance(type_param, TypeVar):
            continue
        arg: Any = args[i]
        # If arg is itself a TypeVar, try to resolve it from existing map
        if isinstance(arg, TypeVar):
            if arg in typevar_map:
                new_map[type_param] = typevar_map[arg]
        else:
            new_map[type_param] = arg
    return new_map


def resolve_typevars(annotation: Any, typevar_map: dict[TypeVar, type[Any]]) -> Any:
    """Substitute TypeVars in a type annotation with concrete types."""
    if not typevar_map:
        return annotation

    # Handle TypeVar directly
    if isinstance(annotation, TypeVar):
        return typevar_map.get(annotation, annotation)

    origin = get_origin(annotation)
    if origin is None:
        return annotation

    args = get_args(annotation)
    if not args:
        return annotation

    # Recursively resolve type arguments
    resolved_args = tuple(resolve_typevars(arg, typevar_map) for arg in args)

    # Check if any args actually changed
    if resolved_args == args:
        return annotation

    # Handle Annotated specially - first arg is the type, rest are metadata
    if origin is Annotated:
        return Annotated[resolved_args]

    # Handle Union types (including T | None)
    if origin is Union:
        return Union[resolved_args]  # noqa: UP007

    # Reconstruct the generic type with resolved arguments
    try:
        return origin[resolved_args]
    except TypeError:
        # Some types don't support subscripting, return as-is
        return annotation
