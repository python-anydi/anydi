from collections.abc import Callable, Iterable
from typing import (
    TYPE_CHECKING,
    Any,
    Concatenate,
    ParamSpec,
    Protocol,
    TypedDict,
    TypeGuard,
    TypeVar,
    overload,
)

from typing_extensions import NotRequired

if TYPE_CHECKING:
    from ._module import Module


from ._types import NOT_SET, Scope

T = TypeVar("T")
P = ParamSpec("P")

ClassT = TypeVar("ClassT", bound=type)
ModuleT = TypeVar("ModuleT", bound="Module")


class ProvidedMetadata(TypedDict):
    """Metadata for classes marked as provided by AnyDI."""

    scope: Scope
    alias: NotRequired[Any]
    from_context: NotRequired[bool]


def _check_already_provided(cls: type) -> None:
    """Check if class already has __provided__ defined directly on it."""
    if "__provided__" in cls.__dict__:
        raise TypeError(
            f"Class `{cls.__name__}` already has `__provided__` defined. "
            "Remove the duplicate scope decorator or manual `__provided__` attribute."
        )


def provided(
    *, scope: Scope, alias: Any = NOT_SET, from_context: bool = False
) -> Callable[[ClassT], ClassT]:
    """Decorator for marking a class as provided by AnyDI with a specific scope."""

    def decorator(cls: ClassT) -> ClassT:
        _check_already_provided(cls)
        metadata: ProvidedMetadata = {"scope": scope}
        if alias is not NOT_SET:
            metadata["alias"] = alias
        if from_context:
            metadata["from_context"] = from_context
        cls.__provided__ = metadata  # type: ignore[attr-defined]
        return cls

    return decorator


@overload
def singleton(cls: ClassT, /) -> ClassT: ...


@overload
def singleton(
    cls: None = None, /, *, alias: Any = NOT_SET
) -> Callable[[ClassT], ClassT]: ...


def singleton(
    cls: ClassT | None = None, /, *, alias: Any = NOT_SET
) -> Callable[[ClassT], ClassT] | ClassT:
    """Decorator for marking a class as a singleton dependency."""

    def decorator(c: ClassT) -> ClassT:
        _check_already_provided(c)
        metadata: ProvidedMetadata = {"scope": "singleton"}
        if alias is not NOT_SET:
            metadata["alias"] = alias
        c.__provided__ = metadata  # type: ignore[attr-defined]
        return c

    if cls is None:
        return decorator

    return decorator(cls)


@overload
def transient(cls: ClassT, /) -> ClassT: ...


@overload
def transient(
    cls: None = None, /, *, alias: Any = NOT_SET
) -> Callable[[ClassT], ClassT]: ...


def transient(
    cls: ClassT | None = None, /, *, alias: Any = NOT_SET
) -> Callable[[ClassT], ClassT] | ClassT:
    """Decorator for marking a class as a transient dependency."""

    def decorator(c: ClassT) -> ClassT:
        _check_already_provided(c)
        metadata: ProvidedMetadata = {"scope": "transient"}
        if alias is not NOT_SET:
            metadata["alias"] = alias
        c.__provided__ = metadata  # type: ignore[attr-defined]
        return c

    if cls is None:
        return decorator

    return decorator(cls)


@overload
def request(cls: ClassT, /, *, from_context: bool = False) -> ClassT: ...


@overload
def request(
    cls: None = None, /, *, alias: Any = NOT_SET, from_context: bool = False
) -> Callable[[ClassT], ClassT]: ...


def request(
    cls: ClassT | None = None,
    /,
    *,
    alias: Any = NOT_SET,
    from_context: bool = False,
) -> Callable[[ClassT], ClassT] | ClassT:
    """Decorator for marking a class as a request-scoped dependency."""

    def decorator(c: ClassT) -> ClassT:
        _check_already_provided(c)
        metadata: ProvidedMetadata = {"scope": "request"}
        if alias is not NOT_SET:
            metadata["alias"] = alias
        if from_context:
            metadata["from_context"] = from_context
        c.__provided__ = metadata  # type: ignore[attr-defined]
        return c

    if cls is None:
        return decorator

    return decorator(cls)


class Provided(Protocol):
    __provided__: ProvidedMetadata


def is_provided(cls: Any) -> TypeGuard[type[Provided]]:
    return hasattr(cls, "__provided__") and "scope" in cls.__provided__


class ProviderMetadata(TypedDict):
    scope: Scope
    override: bool
    alias: NotRequired[Any]


def provider(
    *, scope: Scope, override: bool = False, alias: Any = NOT_SET
) -> Callable[
    [Callable[Concatenate[ModuleT, P], T]], Callable[Concatenate[ModuleT, P], T]
]:
    """Decorator for marking a function or method as a provider in a AnyDI module."""

    def decorator(
        target: Callable[Concatenate[ModuleT, P], T],
    ) -> Callable[Concatenate[ModuleT, P], T]:
        metadata: ProviderMetadata = {"scope": scope, "override": override}
        if alias is not NOT_SET:
            metadata["alias"] = alias
        target.__provider__ = metadata  # type: ignore
        return target

    return decorator


class Provider(Protocol):
    __provider__: ProviderMetadata


def is_provider(obj: Callable[..., Any]) -> TypeGuard[Provider]:
    return hasattr(obj, "__provider__")


class InjectableMetadata(TypedDict):
    tags: Iterable[str] | None


@overload
def injectable(func: Callable[P, T]) -> Callable[P, T]: ...


@overload
def injectable(
    *, tags: Iterable[str] | None = None
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def injectable(
    func: Callable[P, T] | None = None,
    tags: Iterable[str] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]] | Callable[P, T]:
    """Decorator for marking a function or method as requiring dependency injection."""

    def decorator(inner: Callable[P, T]) -> Callable[P, T]:
        inner.__injectable__ = InjectableMetadata(tags=tags)  # type: ignore
        return inner

    if func is None:
        return decorator

    return decorator(func)


class Injectable(Protocol):
    __injectable__: InjectableMetadata


def is_injectable(obj: Callable[..., Any]) -> TypeGuard[Injectable]:
    return hasattr(obj, "__injectable__")
