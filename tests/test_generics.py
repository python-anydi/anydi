from typing import Annotated, Generic, TypeVar, Union

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


def test_build_typevar_map_non_parameterized_base() -> None:
    """Test traversal through non-parameterized base in __orig_bases__."""

    V = TypeVar("V")
    W = TypeVar("W")

    class GenericParent(Generic[V]):
        pass

    class SpecializedParent(GenericParent[User]):
        """This becomes a plain class in Combined's __orig_bases__."""

        pass

    class AnotherGeneric(Generic[W]):
        pass

    class Combined(SpecializedParent, AnotherGeneric[Guest]):
        pass

    typevar_map = build_typevar_map(Combined)
    # V comes from recursing into SpecializedParent
    assert typevar_map[V] is User
    # W comes directly from AnotherGeneric[Guest]
    assert typevar_map[W] is Guest


def test_resolve_typing_union() -> None:
    """Test typing.Union style union (lines 73-74)."""
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(Union[V, str], typevar_map)  # type: ignore  # noqa: UP007
    assert result == Union[User, str]  # noqa: UP007


def test_resolve_typing_union_with_none() -> None:
    """Test typing.Union with None."""
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(Union[V, None], typevar_map)  # type: ignore  # noqa: UP007
    assert result == Union[User, None]  # noqa: UP007


def test_resolve_no_change_returns_original() -> None:
    """Test unchanged args return original annotation."""
    V = TypeVar("V")
    W = TypeVar("W")
    typevar_map = {W: User}  # V is not in the map
    annotation = list[V]  # type: ignore[type-arg]
    result = resolve_typevars(annotation, typevar_map)
    # Since V is not resolved, args don't change, should return original
    assert result is annotation


def test_resolve_dict_type() -> None:
    """Test resolving dict with TypeVars."""
    K = TypeVar("K")
    V = TypeVar("V")
    typevar_map = {K: str, V: User}
    result = resolve_typevars(dict[K, V], typevar_map)  # type: ignore[type-arg]
    assert result == dict[str, User]


def test_resolve_multiple_union_args() -> None:
    """Test union with more than 2 types."""
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(V | str | int, typevar_map)
    assert result == User | str | int


def test_resolve_unchanged_generic_args() -> None:
    """Test that unchanged args return original annotation (line 113)."""
    V = TypeVar("V")
    W = TypeVar("W")
    typevar_map = {W: User}  # V not in map
    original = list[V]  # type: ignore[type-arg]
    result = resolve_typevars(original, typevar_map)
    assert result is original


def test_resolve_origin_without_args() -> None:
    """Test annotation with origin but no args (line 106)."""
    V = TypeVar("V")
    typevar_map = {V: User}
    # Generic class itself has origin but no args
    result = resolve_typevars(Generic, typevar_map)
    assert result is Generic


def test_resolve_union_type_syntax() -> None:
    """Test types.UnionType (| syntax with generics) (lines 78-81)."""
    V = TypeVar("V")
    typevar_map = {V: User}
    # list[V] | int uses types.UnionType as origin
    result = resolve_typevars(list[V] | int, typevar_map)  # type: ignore[type-arg]
    assert result == list[User] | int


def test_resolve_union_type_multiple_args() -> None:
    """Test UnionType with multiple args (loop in lines 79-80)."""
    V = TypeVar("V")
    typevar_map = {V: User}
    result = resolve_typevars(list[V] | int | str, typevar_map)  # type: ignore[type-arg]
    assert result == list[User] | int | str


def test_build_typevar_map_typevar_chain() -> None:
    """Test TypeVar chain resolution."""

    V = TypeVar("V")
    W = TypeVar("W")

    class A(Generic[V]):
        pass

    class B(Generic[W]):
        pass

    class C(A[str], B[V], Generic[V]):
        pass

    typevar_map = build_typevar_map(C)
    assert typevar_map[V] is str
    assert typevar_map[W] is str
