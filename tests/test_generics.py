from typing import Annotated, Generic, TypeVar

from anydi._generics import build_typevar_map, resolve_typevars


# Test classes for build_typevar_map
class Model:
    pass


class User(Model):
    pass


class Guest(Model):
    pass


T = TypeVar("T", bound=Model)
U = TypeVar("U", bound=Model)
T_any = TypeVar("T_any")
U_any = TypeVar("U_any")


class Repository(Generic[T]):
    pass


class Handler(Generic[T]):
    def __init__(self, repo: Repository[T]) -> None:
        self.repo = repo


class UserHandler(Handler[User]):
    pass


# Multi-level inheritance
class BaseService(Generic[T_any]):
    pass


class MiddleService(BaseService[T_any], Generic[T_any]):
    pass


class ConcreteService(MiddleService[User]):
    pass


# Multiple type parameters
class MultiParam(Generic[T_any, U_any]):
    pass


class PartialSpecialized(MultiParam[User, U_any], Generic[U_any]):
    pass


class FullySpecialized(PartialSpecialized[Guest]):
    pass


# Test build_typevar_map
def test_build_typevar_map_basic() -> None:
    typevar_map = build_typevar_map(UserHandler)
    assert len(typevar_map) == 1
    assert typevar_map[T] is User


def test_build_typevar_map_no_generic_base() -> None:
    class PlainClass:
        pass

    typevar_map = build_typevar_map(PlainClass)
    assert typevar_map == {}


def test_build_typevar_map_multi_level() -> None:
    typevar_map = build_typevar_map(ConcreteService)
    assert typevar_map[T_any] is User


def test_build_typevar_map_multiple_params() -> None:
    typevar_map = build_typevar_map(FullySpecialized)
    assert typevar_map[T_any] is User
    assert typevar_map[U_any] is Guest


# Test resolve_typevars
def test_resolve_typevar_directly() -> None:
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(V, typevar_map)
    assert result is User


def test_resolve_typevar_not_in_map() -> None:
    V = TypeVar("V")
    W = TypeVar("W")
    typevar_map = {V: User}
    result = resolve_typevars(W, typevar_map)
    assert result is W  # Should return original TypeVar


def test_resolve_generic_type() -> None:
    typevar_map = {T: User}
    result = resolve_typevars(Repository[T], typevar_map)  # type: ignore[type-arg]
    assert result == Repository[User]


def test_resolve_union_type() -> None:
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(V | None, typevar_map)
    assert result == User | None


def test_resolve_annotated_type() -> None:
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(Annotated[V, "some_metadata"], typevar_map)  # type: ignore[type-arg]
    assert result == Annotated[User, "some_metadata"]


def test_resolve_nested_generic() -> None:
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(list[Repository[V]], typevar_map)  # type: ignore[type-arg]
    assert result == list[Repository[User]]


def test_resolve_empty_map() -> None:
    result = resolve_typevars(Repository[User], {})
    assert result == Repository[User]


def test_resolve_non_generic_type() -> None:
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(str, typevar_map)
    assert result is str


def test_resolve_union_with_nested_generic() -> None:
    """Test that Union types with nested generics are resolved correctly."""
    V = TypeVar("V")
    typevar_map = {V: User}

    result = resolve_typevars(Repository[V] | None, typevar_map)  # type: ignore[type-arg]
    assert result == Repository[User] | None
