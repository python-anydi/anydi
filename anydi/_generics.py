"""Generic TypeVar utilities for resolving type parameters."""

from __future__ import annotations

from types import UnionType
from typing import Annotated, Any, TypeVar, Union, get_args, get_origin


def build_typevar_map(cls: type[Any]) -> dict[TypeVar, type[Any]]:
    """Build a mapping from TypeVars to concrete types for a class."""
    typevar_map: dict[TypeVar, type[Any]] = {}

    orig_bases = getattr(cls, "__orig_bases__", ())

    for base in orig_bases:
        origin = get_origin(base)
        if origin is None:
            # Not a parameterized generic, check if it's a class with bases
            if isinstance(base, type):
                typevar_map.update(build_typevar_map(base))
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
            typevar_map.update(build_typevar_map(origin))
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


def _reconstruct_generic(origin: Any, resolved_args: tuple[Any, ...]) -> Any:
    """Reconstruct a generic type with resolved arguments."""
    # Handle Annotated specially - first arg is the type, rest are metadata
    if origin is Annotated:
        return Annotated[resolved_args]

    # Handle Union types (typing.Union style)
    if origin is Union:
        return Union[resolved_args]  # noqa: UP007

    # Handle Python 3.10+ union types (int | str syntax)
    if origin is UnionType:
        result = resolved_args[0]
        for arg in resolved_args[1:]:
            result = result | arg
        return result

    # Reconstruct the generic type with resolved arguments
    try:
        return origin[resolved_args]
    except TypeError:
        # Some types don't support subscripting, return origin as-is
        return origin


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

    return _reconstruct_generic(origin, resolved_args)
