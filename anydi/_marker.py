"""Provide marker implementation and utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, TypeVar

from ._types import NOT_SET

T = TypeVar("T")


class Marker:
    """Marker stored in annotations or defaults to request injection."""

    __slots__ = ("_attrs", "_current_owner", "_dependency_type", "_preferred_owner")

    _FRAMEWORK_ATTRS = frozenset({"dependency", "use_cache", "cast", "cast_result"})

    def __init__(self, dependency_type: Any = NOT_SET) -> None:
        # Avoid reinitializing attributes when mixins call __init__ multiple times
        if not hasattr(self, "_attrs"):
            super().__init__()
            self._attrs: dict[str, dict[str, Any]] = {}
            self._preferred_owner = "fastapi"
            self._current_owner: str | None = None
        self._dependency_type = dependency_type

    def set_owner(self, owner: str) -> None:
        self._preferred_owner = owner

    def _store_attr(self, name: str, value: Any) -> None:
        owner = self._current_owner or self._preferred_owner
        self._attrs.setdefault(owner, {})[name] = value

    def _get_attr(self, name: str) -> Any:
        owner = self._preferred_owner
        if owner in self._attrs and name in self._attrs[owner]:
            return self._attrs[owner][name]
        for attrs in self._attrs.values():
            if name in attrs:
                return attrs[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._FRAMEWORK_ATTRS and hasattr(self, "_attrs"):
            self._store_attr(name, value)
        else:
            super().__setattr__(name, value)

    def __getattr__(self, name: str) -> Any:
        if name in self._FRAMEWORK_ATTRS and hasattr(self, "_attrs"):
            return self._get_attr(name)
        raise AttributeError(name)

    @property
    def dependency_type(self) -> Any:
        if self._dependency_type is NOT_SET:
            raise TypeError("Dependency type is not set.")
        return self._dependency_type

    @dependency_type.setter
    def dependency_type(self, dependency_type: Any) -> None:
        self._dependency_type = dependency_type

    def __class_getitem__(cls, item: Any) -> Any:
        return Annotated[item, cls()]


_marker_cls: type[Marker] = Marker


def extend_marker(marker_cls: type[Marker]) -> None:
    """Register an additional framework-specific provide marker."""

    global _marker_cls
    previous = _marker_cls

    if previous is Marker:
        _marker_cls = marker_cls
    else:
        name = f"Marker_{marker_cls.__name__}_{previous.__name__}"

        def __init__(self: Marker) -> None:
            marker_cls.__init__(self)
            previous.__init__(self)

        combined: type[Marker] = type(
            name, (marker_cls, previous), {"__init__": __init__}
        )
        _marker_cls = combined


def is_marker(obj: Any) -> bool:
    return isinstance(obj, Marker)


class _ProvideMeta(type):
    """Metaclass for Provide that delegates __class_getitem__ to the active marker."""

    def __getitem__(cls, item: Any) -> Any:
        return _marker_cls.__class_getitem__(item)


if TYPE_CHECKING:
    Provide = Annotated[T, Marker()]

else:

    class Provide(metaclass=_ProvideMeta):
        pass


def Inject() -> Any:
    return _marker_cls()
