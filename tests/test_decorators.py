from abc import ABC, abstractmethod

import pytest

from anydi import Module, injectable, provided, provider, request, singleton, transient
from anydi._decorators import is_injectable, is_provided


class IService(ABC):
    @abstractmethod
    def do_something(self) -> None:
        pass


def test_is_not_provided() -> None:
    class Service:
        pass

    assert not is_provided(Service)


def test_is_not_provided_no_scope() -> None:
    class Service:
        __provided__ = {}

    assert not is_provided(Service)


def test_is_provided_has_scope() -> None:
    class Service:
        __provided__ = {"scope": "singleton"}

    assert is_provided(Service)


# provided decorator tests


def test_provided_decorator() -> None:
    @provided(scope="singleton")
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "singleton",
    }


def test_provided_decorator_with_alias() -> None:
    @provided(scope="singleton", alias=IService)
    class ServiceImpl:
        def do_something(self) -> None:
            pass

    assert is_provided(ServiceImpl)
    assert ServiceImpl.__provided__ == {
        "scope": "singleton",
        "alias": IService,
    }


def test_provided_decorator_with_from_context() -> None:
    @provided(scope="request", from_context=True)
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "request",
        "from_context": True,
    }


# singleton decorator tests


def test_singleton_decorator() -> None:
    @singleton
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "singleton",
    }


def test_singleton_decorator_call() -> None:
    @singleton()
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "singleton",
    }


def test_singleton_decorator_with_alias() -> None:
    @singleton(alias=IService)
    class ServiceImpl:
        def do_something(self) -> None:
            pass

    assert is_provided(ServiceImpl)
    assert ServiceImpl.__provided__ == {
        "alias": IService,
        "scope": "singleton",
    }


def test_singleton_decorator_with_multiple_aliases() -> None:
    class IReader:
        pass

    class IWriter:
        pass

    @singleton(alias=[IReader, IWriter])
    class ReadWriteService:
        pass

    assert is_provided(ReadWriteService)
    assert ReadWriteService.__provided__ == {
        "alias": [IReader, IWriter],
        "scope": "singleton",
    }


# transient decorator tests


def test_transient_decorator() -> None:
    @transient
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "transient",
    }


def test_transient_decorator_call() -> None:
    @transient()
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "transient",
    }


def test_transient_decorator_with_alias() -> None:
    @transient(alias=IService)
    class ServiceImpl:
        def do_something(self) -> None:
            pass

    assert is_provided(ServiceImpl)
    assert ServiceImpl.__provided__ == {
        "alias": IService,
        "scope": "transient",
    }


def test_transient_decorator_invalid_args() -> None:
    with pytest.raises(TypeError):
        transient(from_context=True)  # type: ignore


# request decorator tests


def test_request_decorator() -> None:
    @request
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "request",
    }


def test_request_decorator_call() -> None:
    @request()
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "request",
    }


def test_request_decorator_with_from_context() -> None:
    @request(from_context=True)
    class Service:
        pass

    assert is_provided(Service)
    assert Service.__provided__ == {
        "scope": "request",
        "from_context": True,
    }


def test_request_decorator_with_alias() -> None:
    @request(alias=IService)
    class ServiceImpl:
        def do_something(self) -> None:
            pass

    assert is_provided(ServiceImpl)
    assert ServiceImpl.__provided__ == {
        "alias": IService,
        "scope": "request",
    }


def test_request_decorator_with_alias_and_from_context() -> None:
    @request(alias=IService, from_context=True)
    class ServiceImpl:
        def do_something(self) -> None:
            pass

    assert is_provided(ServiceImpl)
    assert ServiceImpl.__provided__ == {
        "alias": IService,
        "scope": "request",
        "from_context": True,
    }


# duplicate decorator tests


def test_duplicate_provided_decorator_error() -> None:
    with pytest.raises(
        TypeError,
        match="Class `Service` already has `__provided__` defined",
    ):

        @provided(scope="transient")
        @provided(scope="singleton")
        class Service:
            pass


def test_duplicate_singleton_decorator_error() -> None:
    with pytest.raises(
        TypeError,
        match="Class `Service` already has `__provided__` defined",
    ):

        @singleton
        @singleton
        class Service:
            pass


def test_conflicting_scope_decorators_error() -> None:
    with pytest.raises(
        TypeError,
        match="Class `Service` already has `__provided__` defined",
    ):

        @transient
        @singleton
        class Service:
            pass


def test_child_class_can_have_different_scope() -> None:
    @singleton
    class Base:
        pass

    @transient
    class Child(Base):
        pass

    assert getattr(Base, "__provided__") == {"scope": "singleton"}
    assert getattr(Child, "__provided__") == {"scope": "transient"}


def test_decorator_on_class_with_manual_provided_error() -> None:
    with pytest.raises(
        TypeError,
        match="Class `Service` already has `__provided__` defined",
    ):

        @singleton
        class Service:
            __provided__ = {"scope": "transient"}


# provider decorator tests


def test_provider_decorator() -> None:
    class TestModule(Module):
        @provider(scope="singleton", override=True)
        def provide_str(self) -> str:
            return "test"

    assert getattr(TestModule.provide_str, "__provider__") == {
        "scope": "singleton",
        "override": True,
    }


# injectable decorator tests


def test_injectable_decorator() -> None:
    @injectable
    def my_func() -> None:
        pass

    assert is_injectable(my_func)
    assert my_func.__injectable__ == {
        "tags": None,
    }


def test_injectable_decorator_call() -> None:
    @injectable()
    def my_func() -> None:
        pass

    assert is_injectable(my_func)
    assert my_func.__injectable__ == {
        "tags": None,
    }


def test_injectable_decorator_with_tags() -> None:
    @injectable(tags=["tag1", "tag2"])
    def my_func() -> None:
        pass

    assert is_injectable(my_func)
    assert my_func.__injectable__ == {
        "tags": ["tag1", "tag2"],
    }
