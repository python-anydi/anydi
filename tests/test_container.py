import asyncio
import inspect
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Annotated, Any, Generic, TypeVar
from unittest import mock

import pytest
from typing_extensions import Self

from anydi import (
    Container,
    Inject,
    Provide,
    Provider,
    Scope,
    import_container,
    provided,
    request,
    singleton,
    transient,
)
from anydi._resolver import InstanceProxy
from anydi._types import Event

from tests.fixtures import (
    Class,
    Resource,
    Service,
    UniqueId,
    async_event,
    async_generator,
    coro,
    event,
    generator,
    iterator,
)


@pytest.fixture
def container() -> Container:
    return Container()


class TestContainerRegistration:
    """Tests for container Registration functionality."""

    def test_register_provider(self, container: Container) -> None:
        def provider_call() -> str:
            return "test"

        provider = container.register(str, provider_call, scope="transient")

        assert provider.factory == provider_call
        assert provider.scope == "transient"

    def test_provider_decorator(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def ident() -> str:
            return "1000"

        provider = container.providers[str]

        assert provider.factory == ident
        assert provider.scope == "singleton"
        assert provider.dependency_type is str

    def test_register_is_class(self, container: Container) -> None:
        provider = container.register(Class, scope="singleton")

        assert provider.is_class
        assert provider.dependency_type is Class

    def test_register_is_generator(self, container: Container) -> None:
        provider = container.register(factory=generator, scope="singleton")

        assert provider.is_generator
        assert provider.dependency_type is str

    def test_register_is_async_generator(self, container: Container) -> None:
        provider = container.register(factory=async_generator, scope="singleton")

        assert provider.is_async_generator
        assert provider.dependency_type is str

    def test_container_available_as_dependency(self, container: Container) -> None:
        assert container.has_provider_for(Container)
        assert container.resolve(Container) is container

        @container.inject
        def dependent(current: Container = Inject()) -> Container:
            return current

        assert dependent() is container

    def test_register_provider_is_coro(self, container: Container) -> None:
        provider = container.register(factory=coro, scope="singleton")

        assert provider.is_coroutine
        assert provider.dependency_type is str

    @pytest.mark.parametrize(
        ("dependency_type", "expected"),
        [
            (str, str),
            (int, int),
            (Service, Service),
            (Iterator[Service], Service),
            (AsyncIterator[Service], Service),
            (dict[str, Any], dict[str, Any]),
            (list[str], list[str]),
            ("list[str]", list[str]),
            (tuple[str, ...], tuple[str, ...]),
            ("tuple[str, ...]", tuple[str, ...]),
            ('Annotated[str, "name"]', Annotated[str, "name"]),
        ],
    )
    def test_register_dependency_type(
        self, container: Container, dependency_type: type[Any], expected: type[Any]
    ) -> None:
        def call() -> dependency_type:  # type: ignore
            return object()

        provider = container.register(factory=call, scope="singleton")

        assert provider.dependency_type == expected

    def test_register_event(self, container: Container) -> None:
        provider = container.register(factory=event, scope="singleton")

        assert provider.is_generator
        assert issubclass(provider.dependency_type, Event)

    def test_register_async_event(self, container: Container) -> None:
        provider = container.register(factory=async_event, scope="singleton")

        assert provider.is_async_generator
        assert issubclass(provider.dependency_type, Event)

    def test_register_with_dependency_type(self, container: Container) -> None:
        provider = container.register(str, lambda: "hello", scope="singleton")

        assert provider.dependency_type is str

    def test_register_with_none(self, container: Container) -> None:
        with pytest.raises(
            TypeError, match=r"Missing `(.*?)` provider return annotation."
        ):
            container.register(None, lambda: "hello", scope="singleton")

    def test_register_without_return_annotation(self, container: Container) -> None:
        def provide_message():  # type: ignore[no-untyped-def]
            return "hello"

        with pytest.raises(
            TypeError, match=r"Missing `(.*?)` provider return annotation."
        ):
            container.register(factory=provide_message, scope="singleton")

    def test_register_not_callable(self, container: Container) -> None:
        with pytest.raises(
            TypeError,
            match=(
                r"The provider `Test` is invalid because it is not a callable object."
            ),
        ):
            container.register("Test", scope="singleton")  # type: ignore

    def test_register_iterator_no_arg_not_allowed(self, container: Container) -> None:
        with pytest.raises(
            TypeError,
            match=(
                r"Cannot use `(.*?)` resource type annotation without actual "
                "type argument."
            ),
        ):
            container.register(factory=iterator, scope="singleton")

    def test_register_unsupported_scope(self, container: Container) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "The scope `other` is not registered. "
                r"Please register the scope first using register_scope\(\)."
            ),
        ):
            container.register(generator, scope="other")  # type: ignore

    def test_register_transient_resource_not_allowed(
        self, container: Container
    ) -> None:
        with pytest.raises(
            TypeError,
            match=(
                r"The resource provider `(.*?)` is attempting to "
                "register with a transient scope, which is not allowed."
            ),
        ):
            container.register(generator, scope="transient")

    def test_register_without_annotation(self, container: Container) -> None:
        def service_ident() -> str:
            return "10000"

        def service(ident) -> Service:  # type: ignore
            return Service(ident=ident)

        with pytest.raises(
            TypeError, match=r"Missing provider `(.*?)` dependency `ident` annotation."
        ):
            container.register(service, scope="singleton")

    def test_register_positional_only_parameter_not_allowed(
        self, container: Container
    ) -> None:
        def provider_message(a: int, /, b: str) -> str:
            return f"{a} {b}"

        with pytest.raises(
            TypeError,
            match=(
                r"Positional-only parameters are not allowed in the provider `(.*?)`."
            ),
        ):
            container.register(provider_message, scope="singleton")

    def test_register_already_registered(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="singleton")

        with pytest.raises(
            LookupError, match=r"The provider `str` is already registered."
        ):
            container.register(str, lambda: "other", scope="singleton")

    def test_register_override(self, container: Container) -> None:
        container.register(str, lambda: "old", scope="singleton")

        def new_provider_call() -> str:
            return "new"

        provider = container.register(
            str, new_provider_call, scope="singleton", override=True
        )

        assert provider.factory == new_provider_call

    def test_register_named(self, container: Container) -> None:
        container.register(
            Annotated[str, "msg1"],
            lambda: "test1",
            scope="singleton",
        )
        container.register(
            Annotated[str, "msg2"],
            lambda: "test2",
            scope="singleton",
        )

        assert container.is_registered(Annotated[str, "msg1"])
        assert container.is_registered(Annotated[str, "msg2"])

    def test_alias(self, container: Container) -> None:
        class IService:
            pass

        class ServiceImpl(IService):
            pass

        container.register(IService, ServiceImpl, scope="singleton")
        container.alias(ServiceImpl, IService)

        # Both should be considered registered
        assert container.is_registered(IService)
        assert container.is_registered(ServiceImpl)

        # Both should resolve to the same instance
        service1 = container.resolve(IService)
        service2 = container.resolve(ServiceImpl)
        assert service1 is service2
        assert isinstance(service1, ServiceImpl)

    def test_alias_same_type_error(self, container: Container) -> None:
        with pytest.raises(
            ValueError, match=r"Alias type cannot be the same as canonical type."
        ):
            container.alias(str, str)

    def test_alias_duplicate_error(self, container: Container) -> None:
        class IService:
            pass

        class ServiceA:
            pass

        class ServiceB:
            pass

        container.register(ServiceA, scope="singleton")
        container.register(ServiceB, scope="singleton")
        container.alias(IService, ServiceA)

        with pytest.raises(ValueError, match=r"Alias .* is already registered"):
            container.alias(IService, ServiceB)

    def test_alias_unregistered_provider_error(self, container: Container) -> None:
        class IService:
            pass

        class ServiceImpl:
            pass

        with pytest.raises(ValueError, match=r"provider for .* is not registered"):
            container.alias(IService, ServiceImpl)

    def test_alias_after_build_error(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="singleton")
        container.build()

        with pytest.raises(
            RuntimeError,
            match=r"Cannot register aliases after build\(\) has been called.",
        ):
            container.alias(int, str)

    def test_aliases_property(self, container: Container) -> None:
        class IService:
            pass

        class ServiceImpl(IService):
            pass

        container.register(IService, ServiceImpl, scope="singleton")
        container.alias(ServiceImpl, IService)

        assert ServiceImpl in container.aliases
        assert container.aliases[ServiceImpl] == IService

    def test_register_with_alias(self, container: Container) -> None:
        class IService:
            pass

        class ServiceImpl(IService):
            pass

        container.register(ServiceImpl, scope="singleton", alias=IService)

        assert container.is_registered(IService)
        assert container.is_registered(ServiceImpl)

        service1 = container.resolve(IService)
        service2 = container.resolve(ServiceImpl)
        assert service1 is service2
        assert isinstance(service1, ServiceImpl)

    def test_register_with_multiple_aliases(self, container: Container) -> None:
        class IRepository:
            pass

        class IReadRepository:
            pass

        class RepositoryImpl(IRepository, IReadRepository):
            pass

        container.register(
            RepositoryImpl, scope="singleton", alias=[IRepository, IReadRepository]
        )

        assert container.is_registered(IRepository)
        assert container.is_registered(IReadRepository)
        assert container.is_registered(RepositoryImpl)

        repo1 = container.resolve(IRepository)
        repo2 = container.resolve(IReadRepository)
        repo3 = container.resolve(RepositoryImpl)
        assert repo1 is repo2 is repo3

    def test_provider_decorator_with_alias(self, container: Container) -> None:
        class IDatabase:
            pass

        class Database(IDatabase):
            pass

        @container.provider(scope="singleton", alias=IDatabase)
        def provide_database() -> Database:
            return Database()

        assert container.is_registered(IDatabase)
        assert container.is_registered(Database)

        db1 = container.resolve(IDatabase)
        db2 = container.resolve(Database)
        assert db1 is db2

    def test_provider_decorator_with_multiple_aliases(
        self, container: Container
    ) -> None:
        class ICache:
            pass

        class IStore:
            pass

        class RedisCache(ICache, IStore):
            pass

        @container.provider(scope="singleton", alias=[ICache, IStore])
        def provide_cache() -> RedisCache:
            return RedisCache()

        cache1 = container.resolve(ICache)
        cache2 = container.resolve(IStore)
        cache3 = container.resolve(RedisCache)
        assert cache1 is cache2 is cache3

    def test_register_providers_via_constructor(self) -> None:
        container = Container(
            providers=[
                Provider(
                    factory=lambda: "test", scope="singleton", dependency_type=str
                ),
                Provider(factory=lambda: 1, scope="singleton", dependency_type=int),
            ]
        )

        assert container.is_registered(str)
        assert container.is_registered(int)

    def test_register_invalid_transient_resource(self, container: Container) -> None:
        def provider_call() -> Iterator[str]:
            yield "test"

        with pytest.raises(
            TypeError,
            match=(
                r"The resource provider `(.*?)` is attempting to register "
                "with a transient scope, which is not allowed."
            ),
        ):
            container.register(str, provider_call, scope="transient")

    def test_register_invalid_transient_async_resource(
        self,
        container: Container,
    ) -> None:
        async def provider_call() -> AsyncIterator[str]:
            yield "test"

        with pytest.raises(
            TypeError,
            match=(
                r"The resource provider `(.*?)` is attempting to register with a "
                "transient scope, which is not allowed."
            ),
        ):
            container.register(str, provider_call, scope="transient")

    def test_register_valid_resource(self, container: Container) -> None:
        def provider_call1() -> Iterator[str]:
            yield "test"

        def provider_call2() -> Iterator[int]:
            yield 100

        container.register(str, provider_call1, scope="singleton")
        container.register(int, provider_call2, scope="request")

    def test_register_valid_async_resource(self, container: Container) -> None:
        async def provider_call1() -> AsyncIterator[str]:
            yield "test"

        async def provider_call2() -> AsyncIterator[int]:
            yield 100

        container.register(str, provider_call1, scope="singleton")
        container.register(int, provider_call2, scope="request")

    def test_register_invalid_provider_type(self, container: Container) -> None:
        with pytest.raises(
            TypeError,
            match=(
                r"The provider `Test` is invalid because it is not a callable object."
            ),
        ):
            container.register(str, "Test", scope="singleton")  # type: ignore

    @pytest.mark.parametrize(
        ("scope1", "scope2", "scope3", "valid"),
        [
            ("transient", "transient", "transient", True),
            ("transient", "transient", "singleton", True),
            ("transient", "transient", "request", True),
            ("transient", "singleton", "transient", False),
            ("transient", "singleton", "singleton", True),
            ("transient", "singleton", "request", False),
            ("transient", "request", "transient", False),
            ("transient", "request", "singleton", True),
            ("transient", "request", "request", True),
            ("singleton", "transient", "transient", False),
            ("singleton", "transient", "singleton", False),
            ("singleton", "transient", "request", False),
            ("singleton", "singleton", "transient", False),
            ("singleton", "singleton", "singleton", True),
            ("singleton", "singleton", "request", False),
            ("singleton", "request", "transient", False),
            ("singleton", "request", "singleton", False),
            ("singleton", "request", "request", False),
            ("request", "transient", "transient", False),
            ("request", "transient", "singleton", False),
            ("request", "transient", "request", False),
            ("request", "singleton", "transient", False),
            ("request", "singleton", "singleton", True),
            ("request", "singleton", "request", False),
            ("request", "request", "transient", False),
            ("request", "request", "singleton", True),
            ("request", "request", "request", True),
        ],
    )
    def test_register_match_scopes(
        self,
        container: Container,
        scope1: Scope,
        scope2: Scope,
        scope3: Scope,
        valid: bool,
    ) -> None:
        def a() -> int:
            return 2

        def b(a: int) -> float:
            return a * 2.5

        def mixed(a: int, b: float) -> str:
            return f"{a} * {b} = {a * b}"

        container.register(int, a, scope=scope3)
        container.register(float, b, scope=scope2)
        container.register(str, mixed, scope=scope1)

        try:
            container.build()
        except ValueError:
            result = False
        else:
            result = True

        assert result == valid

    def test_register_match_scopes_error(self, container: Container) -> None:
        def provider_int() -> int:
            return 1000

        def provider_str(n: int) -> str:
            return f"{n}"

        container.register(int, provider_int, scope="request")
        container.register(str, provider_str, scope="singleton")

        with pytest.raises(
            ValueError,
            match=(
                r"The provider `(.*?)` with a `singleton` scope cannot depend on "
                r"`(.*?)` with a `request` scope. Please ensure all providers are "
                "registered with matching scopes."
            ),
        ):
            container.build()

    def test_register_with_not_registered_sub_provider(
        self,
        container: Container,
    ) -> None:
        def dep2(dep1: int) -> str:
            return str(dep1)

        container.register(str, dep2, scope="singleton")

        with pytest.raises(
            LookupError,
            match=(
                r"The provider `str \(via (.*?)\.dep2\)` depends on `dep1` of type "
                r"`int`, which has not been registered or set. To resolve this, "
                r"ensure that `dep1` is registered before "
                r"calling build\(\), or register it with `from_context=True` "
                r"if it should be provided via scoped context."
            ),
        ):
            container.build()

    def test_register_events(self, container: Container) -> None:
        events = []

        @container.provider(scope="singleton")
        def message() -> str:
            return "test"

        @container.provider(scope="singleton")
        def event_1(message: str) -> Iterator[None]:
            events.append(f"event_1: before {message}")
            yield
            events.append(f"event_1: after {message}")

        @container.provider(scope="request")
        def event_2(message: str) -> Iterator[None]:
            events.append(f"event_2: before {message}")
            yield
            events.append(f"event_2: after {message}")

        # Ensure that non-event is not called
        @container.provider(scope="request")
        def non_event(message: str) -> Iterator[int]:
            events.append(f"non_event: before {message}")
            yield 1
            events.append(f"non_event: after {message}")

        with container, container.request_context():
            assert events == [
                "event_1: before test",
                "event_2: before test",
            ]

        assert events == [
            "event_1: before test",
            "event_2: before test",
            "event_2: after test",
            "event_1: after test",
        ]

    async def test_register_async_events(self, container: Container) -> None:
        events = []

        @container.provider(scope="singleton")
        def message() -> str:
            return "test"

        @container.provider(scope="singleton")
        async def event_1(message: str) -> AsyncIterator[None]:
            events.append(f"event_1: before {message}")
            yield
            events.append(f"event_1: after {message}")

        @container.provider(scope="request")
        def event_2(message: str) -> Iterator[None]:
            events.append(f"event_2: before {message}")
            yield
            events.append(f"event_2: after {message}")

        # Ensure that non-event is not called
        @container.provider(scope="request")
        async def non_event(message: str) -> AsyncIterator[int]:
            events.append(f"non_event: before {message}")
            yield 1
            events.append(f"non_event: after {message}")

        async with container, container.arequest_context():
            assert events == [
                "event_1: before test",
                "event_2: before test",
            ]

        assert events == [
            "event_1: before test",
            "event_2: before test",
            "event_2: after test",
            "event_1: after test",
        ]

    def test_register_provider_unresolved_parameter_with_defaults(
        self, container: Container
    ) -> None:
        """Test registering a provider with an unresolved parameter with default."""

        def provider_with_default(param: int = 10) -> str:
            return str(param)

        # Should not raise an error because `param` has a default
        container.register(str, provider_with_default, scope="singleton")
        assert container.resolve(str) == "10"

    def test_register_provider_unresolved_parameter_with_defaults_dict(
        self, container: Container
    ) -> None:
        """Test registering a provider with an unresolved parameter with defaults."""

        @singleton
        class ServiceWithParam:
            def __init__(self, param: int) -> None:
                self.param = param

        # 'param' is not registered in container, but provided via defaults
        service = container.create(ServiceWithParam, param=20)
        assert service.param == 20

    def test_register_provider_unresolved_parameter_raises(
        self, container: Container
    ) -> None:
        """Test registering a provider with an unresolved parameter raises."""

        def provider_with_param(param: int) -> str:
            return str(param)

        container.register(str, provider_with_param, scope="singleton")

        with pytest.raises(
            LookupError, match=r"The provider `(.*?)` depends on `param` of type `int`"
        ):
            container.resolve(str)

    def test_register_provider_scope_mismatch(self, container: Container) -> None:
        """Test that registering a provider with a scope mismatch raises ValueError."""
        container.register(int, lambda: 1, scope="request")

        def provider_singleton(param: int) -> str:
            return str(param)

        container.register(str, provider_singleton, scope="singleton")

        with pytest.raises(
            ValueError,
            match=r"The provider `(.*?)` with a `singleton` scope cannot depend on",
        ):
            container.resolve(str)

    def test_from_context_singleton_scope_raises(self, container: Container) -> None:
        """Test that from_context=True with singleton scope raises ValueError."""
        with pytest.raises(
            ValueError,
            match=(
                "The `from_context=True` option cannot be used with `singleton` scope"
            ),
        ):
            container.register(int, scope="singleton", from_context=True)

    def test_from_context_transient_scope_raises(self, container: Container) -> None:
        """Test that from_context=True with transient scope raises ValueError."""
        with pytest.raises(
            ValueError,
            match=(
                "The `from_context=True` option cannot be used with `transient` scope"
            ),
        ):
            container.register(int, scope="transient", from_context=True)

    def test_from_context_missing_dependency_type(self, container: Container) -> None:
        """Test that from_context=True without dependency_type raises TypeError."""
        with pytest.raises(
            TypeError,
            match=(
                "The `dependency_type` parameter is required "
                "when using `from_context=True`"
            ),
        ):
            container.register(scope="request", from_context=True)

    def test_from_context_already_registered(self, container: Container) -> None:
        """Test registering duplicate from_context provider raises LookupError."""
        container.register(int, scope="request", from_context=True)
        with pytest.raises(
            LookupError, match="The provider `int` is already registered"
        ):
            container.register(int, scope="request", from_context=True)

    def test_register_provider_defaults_handling(self, container: Container) -> None:
        """Test that defaults are correctly handled in _register_provider logic."""

        @singleton
        class MyService:
            def __init__(self, a: int) -> None:
                self.a = a

        # Using create to trigger registration with defaults
        service = container.create(MyService, a=100)
        assert service.a == 100

    def test_unregister_provider(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="singleton")

        assert container.is_registered(str)

        container.unregister(str)

        assert not container.is_registered(str)

    def test_unregister_provider_resource(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def message() -> Iterator[str]:
            yield "test"

        assert container.is_registered(str)
        assert str in container._resources["singleton"]

        container.unregister(str)

        assert not container.is_registered(str)
        assert str not in container._resources["singleton"]

    def test_unregister_request_scoped_provider(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="request")

        assert container.is_registered(str)

        container.unregister(str)

        assert not container.is_registered(str)

    def test_unregister_not_registered_provider(self, container: Container) -> None:
        with pytest.raises(LookupError, match=r"The provider `str` is not registered."):
            container.unregister(str)

    def test_unregister_provider_removes_aliases(self, container: Container) -> None:
        class IService:
            pass

        class ServiceImpl(IService):
            pass

        container.register(ServiceImpl, scope="singleton", alias=IService)

        assert container.is_registered(ServiceImpl)
        assert container.is_registered(IService)
        assert IService in container.aliases

        container.unregister(ServiceImpl)

        assert not container.is_registered(ServiceImpl)
        assert not container.is_registered(IService)
        assert IService not in container.aliases

    # Lifespan

    def test_container_with_modules_in_constructor(self) -> None:
        """Test passing modules in Container constructor."""

        @singleton
        class Service:
            pass

        def setup_module(container: Container) -> None:
            container.register(Service)

        container = Container(modules=[setup_module])
        assert container.has_provider_for(Service)

    def test_register_module_directly(self) -> None:
        """Test calling register_module() directly."""
        container = Container()

        @singleton
        class DirectService:
            pass

        def setup_module(container: Container) -> None:
            container.register(DirectService)

        container.register_module(setup_module)
        assert container.has_provider_for(DirectService)


class TestContainerBuild:
    """Tests for container Build functionality."""

    def test_build_locks_registration(self) -> None:
        """Test that registration is locked after build()."""

        @singleton
        class Service:
            pass

        container = Container()
        container.register(Service)
        container.build()

        # Try to register after build
        @singleton
        class AnotherService:
            pass

        with pytest.raises(
            RuntimeError,
            match=r"Cannot register providers after build\(\) has been called.",
        ):
            container.register(AnotherService)

    def test_build_allows_override_after_build(self) -> None:
        """Test that override=True allows registration after build()."""

        @singleton
        class Service:
            pass

        container = Container()
        container.register(Service)
        container.build()

        # Override should work even after build
        @singleton
        class MockService:
            pass

        container.register(Service, MockService, override=True)
        assert container.resolve(Service).__class__.__name__ == "MockService"

    def test_build_override_provider_with_dependencies_after_build(self) -> None:
        """Test override provider with dependencies resolves correctly after build()."""

        @singleton
        class Config:
            value = "config"

        @singleton
        class Service:
            def __init__(self, config: Config) -> None:
                self.config = config

            def get_data(self) -> str:
                return f"original: {self.config.value}"

        container = Container()
        container.register(Config)
        container.register(Service)
        container.build()

        # Override with a provider that has dependencies
        @container.provider(scope="singleton", override=True)
        def mock_service(config: Config) -> Service:
            class MockService(Service):
                def get_data(self) -> str:
                    return f"mocked: {self.config.value}"

            return MockService(config)

        service = container.resolve(Service)
        assert service.get_data() == "mocked: config"

    def test_build_twice_raises_error(self) -> None:
        """Test that calling build() twice raises RuntimeError."""

        @singleton
        class Service:
            pass

        container = Container()
        container.register(Service)
        container.build()

        with pytest.raises(RuntimeError, match="Container has already been built"):
            container.build()

    def test_build_detects_circular_dependencies(self) -> None:
        """Test that build() detects circular dependencies."""
        container = Container()

        class ServiceA:
            pass

        class ServiceB:
            pass

        class ServiceC:
            pass

        # Register providers with circular dependencies
        @container.provider(scope="singleton")
        def provide_a(b: ServiceB) -> ServiceA:
            return ServiceA()

        @container.provider(scope="singleton")
        def provide_b(c: ServiceC) -> ServiceB:
            return ServiceB()

        @container.provider(scope="singleton")
        def provide_c(a: ServiceA) -> ServiceC:
            return ServiceC()

        # Build should detect the circular dependency
        with pytest.raises(
            ValueError,
            match=(
                r"Circular dependency detected: .* -> .* -> .*\. "
                r"Please restructure your dependencies to break the cycle\."
            ),
        ):
            container.build()

    def test_build_with_provided_auto_registration(self) -> None:
        """Test that @provided classes are auto-registered during build()."""

        @singleton
        class AutoService:
            pass

        @singleton
        class DependentService:
            def __init__(self, auto: AutoService) -> None:
                self.auto = auto

        container = Container()
        container.register(DependentService)
        container.build()

        # AutoService should be auto-registered
        assert container.has_provider_for(AutoService)
        service = container.resolve(DependentService)
        assert isinstance(service.auto, AutoService)

    def test_build_resolve_unregistered_provided_class_after_build(self) -> None:
        """Test resolving an unregistered @provided class after build()."""

        @singleton
        class Repository:
            def get_data(self) -> str:
                return "data"

        @request
        class Handler:
            def __init__(self, repo: Repository) -> None:
                self.repo = repo

        container = Container()
        container.register(Repository)
        # Handler is NOT registered - relies on auto-discovery via @request
        container.build()
        container.start()

        try:
            with container.request_context():
                handler = container.resolve(Handler)
                assert isinstance(handler, Handler)
                assert isinstance(handler.repo, Repository)
                assert handler.repo.get_data() == "data"
        finally:
            container.close()

    def test_build_with_parameter_defaults(self) -> None:
        """Test build() handles parameters with defaults correctly."""
        container = Container()

        @singleton
        class OptionalDep:
            pass

        @container.provider(scope="singleton")
        def service_with_default(opt: OptionalDep | None = None) -> str:
            return "has_default"

        # OptionalDep is not registered, but has default
        container.build()

        result = container.resolve(str)
        assert result == "has_default"

    def test_build_with_request_scoped_from_context_dependency(self) -> None:
        """Test build() with request-scoped provider having from_context dependency."""
        container = Container()

        class ExternalData:
            def __init__(self, value: str) -> None:
                self.value = value

        class RequestService:
            def __init__(self, data: ExternalData) -> None:
                self.data = data

        # Register ExternalData as from_context (will be provided via context.set)
        container.register(ExternalData, scope="request", from_context=True)

        @container.provider(scope="request")
        def provide_service(data: ExternalData) -> RequestService:
            return RequestService(data)

        # Build should succeed
        container.build()

        # Resolution should fail without context.set()
        with pytest.raises(
            LookupError, match=r"from_context=True but has not been set"
        ):
            with container.request_context():
                container.resolve(RequestService)

        # Resolution should succeed with context.set()
        with container.request_context() as ctx:
            ctx.set(ExternalData, ExternalData(value="test"))
            result = container.resolve(RequestService)
            assert result.data.value == "test"

    def test_build_already_resolved_parameters(self) -> None:
        """Test build() skips already-resolved parameters."""
        container = Container()

        @singleton
        class DepA:
            pass

        @singleton
        class DepB:
            pass

        @singleton
        class Service:
            def __init__(self, a: DepA, b: DepB) -> None:
                self.a = a
                self.b = b

        container.register(DepA)
        container.register(DepB)
        container.register(Service)

        # Build once to resolve
        container.build()

        # Verify service can be resolved
        service = container.resolve(Service)
        assert isinstance(service.a, DepA)
        assert isinstance(service.b, DepB)

    def test_build_after_on_the_fly_resolution(self) -> None:
        """Test build() after some providers already resolved on-the-fly."""
        container = Container()

        @singleton
        class DepA:
            pass

        @singleton
        class DepB:
            pass

        @singleton
        class ServiceX:
            pass

        @singleton
        class ServiceY:
            pass

        @container.provider(scope="singleton")
        def provide_x(a: DepA) -> ServiceX:
            return ServiceX()

        @container.provider(scope="singleton")
        def provide_y(b: DepB) -> ServiceY:
            return ServiceY()

        container.register(DepA)
        container.register(DepB)

        # Resolve ServiceX on-the-fly (this resolves DepA)
        container.resolve(ServiceX)

        # Now call build() - ServiceX and DepA are already resolved
        # This hits the already-resolved parameter path (lines 876-877)
        container.build()

        # Verify both services work
        assert isinstance(container.resolve(ServiceY), ServiceY)


class TestContainerResolution:
    """Tests for container Resolution functionality."""

    def test_resolve_singleton_scoped(self, container: Container) -> None:
        instance = "test"

        container.register(str, lambda: instance, scope="singleton")

        assert container.resolve(str) == instance

    def test_resolve_singleton_scoped_not_started(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def message() -> Iterator[str]:
            yield "test"

        assert container.resolve(str) == "test"

    def test_resolve_singleton_scoped_resource(self, container: Container) -> None:
        instance = "test"

        def provide() -> Iterator[str]:
            yield instance

        container.register(str, provide, scope="singleton")
        container.start()

        assert container.resolve(str) == instance

    def test_resolve_singleton_scoped_started_with_async_resource_provider(
        self,
        container: Container,
    ) -> None:
        instance = "test"

        async def provide() -> AsyncIterator[str]:
            yield instance

        container.register(str, provide, scope="singleton")

        with pytest.raises(
            TypeError,
            match=(
                r"The instance for the provider `str` cannot be created "
                "in synchronous mode."
            ),
        ):
            container.start()

    def test_resolve_singleton_resource(self, container: Container) -> None:
        instance = "test"

        def provide() -> Iterator[str]:
            yield instance

        container.register(str, provide, scope="singleton")

        container.resolve(str)

    def test_resolve_singleton_scoped_thread_safe(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def provide_unique_id() -> UniqueId:
            return UniqueId()

        unique_ids = set()

        def use_unique_id() -> None:
            unique_id = container.resolve(UniqueId)
            unique_ids.add(unique_id)

        threads = [threading.Thread(target=use_unique_id) for _ in range(10)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert len(unique_ids) == 1

    async def test_resolve_singleton_async_resource(self, container: Container) -> None:
        instance = "test"

        def provide() -> Iterator[str]:
            yield instance

        container.register(str, provide, scope="singleton")

        await container.astart()

        assert container.resolve(str) == instance

    async def test_resolve_singleton_async_and_sync_resources(
        self, container: Container
    ) -> None:
        instance_str = "test"
        instance_int = 100

        def provider_1() -> Iterator[str]:
            yield instance_str

        async def provider_2() -> AsyncIterator[int]:
            yield instance_int

        container.register(str, provider_1, scope="singleton")
        container.register(int, provider_2, scope="singleton")

        await container.astart()

        assert container.resolve(str) == instance_str
        assert container.resolve(int) == instance_int

    async def test_resolved_singleton_async_resource_not_started(
        self,
        container: Container,
    ) -> None:
        instance = "test"

        async def provide() -> AsyncIterator[str]:
            yield instance

        container.register(str, provide, scope="singleton")

        with pytest.raises(
            TypeError,
            match=(
                r"The instance for the provider `str` cannot be created "
                "in synchronous mode."
            ),
        ):
            container.resolve(str)

    def test_resolve_singleton_annotated_resource(self, container: Container) -> None:
        instance = "test"

        @container.provider(scope="singleton")
        def provide() -> Iterator[Annotated[str, "message"]]:
            yield instance

        result = container.resolve(Annotated[str, "message"])

        assert result == instance

    async def test_resolve_singleton_annotated_async_resource(
        self, container: Container
    ) -> None:
        instance = "test"

        @container.provider(scope="singleton")
        async def provide() -> AsyncIterator[Annotated[str, "message"]]:
            yield instance

        result = await container.aresolve(Annotated[str, "message"])

        assert result == instance

    async def test_resolve_singleton_scoped_coro_safe(
        self, container: Container
    ) -> None:
        @container.provider(scope="singleton")
        async def provide_unique_id() -> UniqueId:
            return UniqueId()

        unique_ids = set()

        async def use_service() -> None:
            unique_id = await container.aresolve(UniqueId)
            unique_ids.add(unique_id)

        tasks = [use_service() for _ in range(10)]

        await asyncio.gather(*tasks)

        assert len(unique_ids) == 1

    async def test_resolve_scoped_coro_safe(self, container: Container) -> None:
        @container.provider(scope="request")
        async def provide_unique_id() -> UniqueId:
            return UniqueId()

        unique_ids = set()

        async def use_unique_id() -> None:
            async with container.arequest_context():
                unique_id = await container.aresolve(UniqueId)
                unique_ids.add(unique_id)

        tasks = [use_unique_id() for _ in range(10)]
        await asyncio.gather(*tasks)

        assert len(unique_ids) == 10

    def test_resolve_request_scoped(self, container: Container) -> None:
        instance = "test"

        container.register(str, lambda: instance, scope="request")

        with container.request_context():
            assert container.resolve(str) == instance

    def test_resolve_request_scoped_not_started(self, container: Container) -> None:
        instance = "test"

        container.register(str, lambda: instance, scope="request")

        with pytest.raises(
            LookupError,
            match=(
                r"The request context has not been started. Please ensure that the "
                "request context is properly initialized before attempting to use it."
            ),
        ):
            container.resolve(str)

    def test_resolve_request_scoped_annotated_resource(
        self, container: Container
    ) -> None:
        instance = "test"

        @container.provider(scope="request")
        def provide() -> Iterator[Annotated[str, "message"]]:
            yield instance

        with container.request_context():
            result = container.resolve(Annotated[str, "message"])

        assert result == instance

    async def test_resolve_request_scoped_annotated_async_resource(
        self,
        container: Container,
    ) -> None:
        instance = "test"

        @container.provider(scope="request")
        async def provide() -> AsyncIterator[Annotated[str, "message"]]:
            yield instance

        async with container.arequest_context():
            result = await container.aresolve(Annotated[str, "message"])

        assert result == instance

    def test_resolve_request_scoped_from_context(self, container: Container) -> None:
        class Request:
            def __init__(self, path: str) -> None:
                self.path = path

        container.register(Request, scope="request", from_context=True)

        @container.provider(scope="request")
        def req_path(req: Request) -> str:
            return req.path

        with container.request_context() as context:
            context.set(Request, Request(path="test"))
            assert container.resolve(str) == "test"

    def test_resolve_request_scoped_from_context_not_set(
        self, container: Container
    ) -> None:
        class Request:
            def __init__(self, path: str) -> None:
                self.path = path

        container.register(Request, scope="request", from_context=True)

        @container.provider(scope="request")
        def req_path(req: Request) -> str:
            return req.path

        with (
            pytest.raises(
                LookupError,
                match=(
                    r"The provider `.*Request` is registered with "
                    r"from_context=True but has not been set in the request context."
                ),
            ),
            container.request_context(),
        ):
            container.resolve(str)

    def test_resolve_request_scoped_with_from_context_dependency(
        self, container: Container
    ) -> None:
        class ExternalRequest:
            def __init__(self, rid: str) -> None:
                self.rid = rid

        class RequestContext:
            def __init__(self, *, request: ExternalRequest) -> None:
                self.request = request

        container.register(ExternalRequest, scope="request", from_context=True)

        @container.provider(scope="request")
        def request_context(request: ExternalRequest) -> RequestContext:
            return RequestContext(request=request)

        with container.request_context() as ctx:
            req = ExternalRequest(rid="req-1")
            ctx.set(ExternalRequest, req)

            result = container.resolve(RequestContext)
            assert result.request.rid == "req-1"

    def test_register_from_context_with_singleton_scope_error(
        self, container: Container
    ) -> None:
        class MyService:
            pass

        with pytest.raises(
            ValueError,
            match=r"from_context=True.*cannot be used with.*singleton.*scope",
        ):
            container.register(MyService, scope="singleton", from_context=True)

    def test_register_from_context_with_transient_scope_error(
        self, container: Container
    ) -> None:
        class MyService:
            pass

        with pytest.raises(
            ValueError,
            match=r"from_context=True.*cannot be used with.*transient.*scope",
        ):
            container.register(MyService, scope="transient", from_context=True)

    def test_register_from_context_already_registered_error(
        self, container: Container
    ) -> None:
        class Request:
            pass

        container.register(Request, scope="request", from_context=True)

        with pytest.raises(
            LookupError,
            match=r"The provider .*Request.* is already registered",
        ):
            container.register(Request, scope="request", from_context=True)

    async def test_aresolve_request_scoped_from_context(
        self, container: Container
    ) -> None:
        class Request:
            def __init__(self, path: str) -> None:
                self.path = path

        container.register(Request, scope="request", from_context=True)

        @container.provider(scope="request")
        def req_path(req: Request) -> str:
            return req.path

        async with container.arequest_context() as ctx:
            ctx.set(Request, Request(path="/async-test"))
            result = await container.aresolve(str)
            assert result == "/async-test"

    async def test_aresolve_request_scoped_from_context_not_set(
        self, container: Container
    ) -> None:
        class Request:
            pass

        container.register(Request, scope="request", from_context=True)

        with pytest.raises(
            LookupError,
            match=r"from_context=True but has not been set in the request context",
        ):
            async with container.arequest_context():
                await container.aresolve(Request)

    def test_resolve_with_inject_marker_as_default(self, container: Container) -> None:
        """Test that Inject() marker as default triggers resolution, not default use."""

        @singleton
        class Config:
            value = "test-config"

        @singleton
        class Service:
            def __init__(self, config: Config = Inject()) -> None:
                self.config = config

        result = container.resolve(Service)
        assert isinstance(result.config, Config)
        assert result.config.value == "test-config"

    def test_resolve_request_scoped_auto_nested_dependencies(
        self, container: Container
    ) -> None:
        @request
        class Repository:
            pass

        @request
        class Service:
            def __init__(self, repository: Repository) -> None:
                self.repository = repository

        with container.request_context():
            result = container.resolve(Service)

        assert isinstance(result, Service)
        assert isinstance(result.repository, Repository)

    async def test_aresolve_request_scoped_auto_nested_dependencies(
        self, container: Container
    ) -> None:
        @request
        class Repository:
            pass

        @request
        class Service:
            def __init__(self, repository: Repository) -> None:
                self.repository = repository

        async with container.arequest_context():
            result = await container.aresolve(Service)

        assert isinstance(result, Service)
        assert isinstance(result.repository, Repository)

    def test_resolve_scoped_thread_safe(self, container: Container) -> None:
        @container.provider(scope="request")
        def provide_unique_id() -> UniqueId:
            return UniqueId()

        unique_ids = set()

        def use_unique_id() -> None:
            with container.request_context():
                unique_id = container.resolve(UniqueId)
                unique_ids.add(unique_id)

        threads = [threading.Thread(target=use_unique_id) for n in range(10)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert len(unique_ids) == 10

    def test_resolve_transient_scoped(self, container: Container) -> None:
        container.register(uuid.UUID, uuid.uuid4, scope="transient")

        assert container.resolve(uuid.UUID) != container.resolve(uuid.UUID)

    def test_sync_resolve_transient_async_provider(self, container: Container) -> None:
        @container.provider(scope="transient")
        async def get_uuid() -> uuid.UUID:
            return uuid.uuid4()

        with pytest.raises(
            TypeError,
            match=(
                r"The instance for the provider `uuid.UUID` cannot "
                "be created in synchronous mode."
            ),
        ):
            container.resolve(uuid.UUID)

    async def test_async_resolve_transient_provider(self, container: Container) -> None:
        @container.provider(scope="transient")
        async def get_uuid() -> uuid.UUID:
            return uuid.uuid4()

        assert await container.aresolve(uuid.UUID) != await container.aresolve(
            uuid.UUID
        )

    async def test_async_resolve_synchronous_resource(
        self, container: Container
    ) -> None:
        @container.provider(scope="singleton")
        def msg() -> Iterator[str]:
            yield "test"

        assert await container.aresolve(str) == "test"

    def test_resolve_not_registered_instance(self, container: Container) -> None:
        with pytest.raises(
            LookupError,
            match=(
                r"The provider `str` is either not registered, not provided, "
                "or not set in the scoped context. Please ensure that the provider "
                "is properly registered and that the class is decorated "
                "with a scope before attempting to use it."
            ),
        ):
            container.resolve(str)

    def test_resolve_provider_scope_defined(self, container: Container) -> None:
        @singleton
        class Service:
            pass

        _ = container.resolve(Service)

        provider = container.providers[Service]

        assert provider.factory == Service
        assert provider.scope == "singleton"
        assert provider.dependency_type == Service

    def test_resolve_provider_scope_from_sub_provider_request(
        self,
        container: Container,
    ) -> None:
        @container.provider(scope="request")
        def ident() -> str:
            return "test"

        @request
        class Service:
            def __init__(self, ident: str) -> None:
                self.ident = ident

        with container.request_context():
            _ = container.resolve(Service)

        assert Service in container.providers

        provider = container.providers[str]

        assert provider.factory == ident
        assert provider.scope == "request"
        assert provider.dependency_type is str

    def test_resolve_nested_singleton_provider(self, container: Container) -> None:
        @singleton
        class Repository:
            pass

        @singleton
        class Service:
            def __init__(self, repository: Repository) -> None:
                self.repository = repository

        with container.request_context():
            _ = container.resolve(Service)

        assert container.providers[Service].scope == "singleton"

    def test_resolve_singleton_in_scoped_context(self, container: Container) -> None:
        @singleton
        class Database:
            def __init__(self) -> None:
                self.id = uuid.uuid4()

        @container.provider(scope="request")
        def provide_connection(db: Database) -> Iterator[str]:
            # The database instance used here should be the same as resolved directly
            yield f"conn-{db.id}"

        with container.request_context():
            # Resolve the singleton directly
            db1 = container.resolve(Database)

            # Resolve the request-scoped provider which depends on the singleton
            conn = container.resolve(str)

            # Resolve the singleton again
            db2 = container.resolve(Database)

            # All should use the same Database instance
            assert db1 is db2
            assert conn == f"conn-{db1.id}"

    async def test_async_resolve_singleton_in_scoped_contextr(
        self, container: Container
    ) -> None:
        @singleton
        class Database:
            def __init__(self) -> None:
                self.id = uuid.uuid4()

        @container.provider(scope="request")
        async def provide_connection(db: Database) -> AsyncIterator[str]:
            # The database instance used here should be the same as resolved directly
            yield f"conn-{db.id}"

        async with container.arequest_context():
            # Resolve the singleton directly
            db1 = await container.aresolve(Database)

            # Resolve the request-scoped provider which depends on the singleton
            conn = await container.aresolve(str)

            # Resolve the singleton again
            db2 = await container.aresolve(Database)

            # All should use the same Database instance
            assert db1 is db2
            assert conn == f"conn-{db1.id}"

    def test_resolve_singleton_in_scope_context_from_async_provider(
        self, container: Container
    ) -> None:
        @singleton
        class Database:
            def __init__(self) -> None:
                self.id = uuid.uuid4()

        @container.provider(scope="request")
        async def provide_connection(db: Database) -> AsyncIterator[str]:
            yield f"conn-{db.id}"

        with container.request_context():
            # Resolve the singleton directly in sync mode
            db = container.resolve(Database)

            # The singleton should have the expected id
            assert isinstance(db.id, uuid.UUID)

    async def test_async_resolve_singleton_in_async_scope_context_from_sync_provider(
        self, container: Container
    ) -> None:
        @singleton
        class Database:
            def __init__(self) -> None:
                self.id = uuid.uuid4()

        @container.provider(scope="request")
        def provide_connection(db: Database) -> Iterator[str]:
            yield f"conn-{db.id}"

        async with container.arequest_context():
            # Resolve the singleton directly in async mode
            db = await container.aresolve(Database)

            # Resolve the request-scoped provider which depends on the singleton
            conn = await container.aresolve(str)

            # The singleton should be reused
            assert conn == f"conn-{db.id}"

    def test_resolve_with_primitive_class(self, container: Container) -> None:
        @singleton
        class Service:
            def __init__(self, name: str) -> None:
                self.name = name

        with pytest.raises(
            LookupError,
            match=(
                r"The provider `(.*?)` depends on `name` of type "
                r"`str`, which has not been registered or set. To resolve this, "
                r"ensure that `name` is registered before "
                r"(calling build\(\)|resolving)."
            ),
        ):
            container.resolve(Service)

    def test_resolve_with_as_context_manager(self, container: Container) -> None:
        @singleton
        class Resource:
            def __init__(self) -> None:
                self.entered = False
                self.exited = False

            def __enter__(self) -> Self:
                self.entered = True
                return self

            def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
                self.exited = True

        resource = container.resolve(Resource)

        assert resource.entered

        container.close()

        assert resource.exited

    async def test_resolve_with_as_async_context_manager(
        self,
        container: Container,
    ) -> None:
        @singleton
        class Service:
            def __init__(self) -> None:
                self.entered = False
                self.exited = False

            async def __aenter__(self) -> Self:
                self.entered = True
                return self

            async def __aexit__(
                self, exc_type: Any, exc_value: Any, traceback: Any
            ) -> None:
                self.exited = True

        service = await container.aresolve(Service)

        assert service.entered

        await container.aclose()

        assert service.exited

    def test_resolve_with_defaults(self, container: Container) -> None:
        @singleton
        class Repo:
            def __init__(self, name: str = "repo") -> None:
                self.name = name

        @singleton
        class Service:
            def __init__(self, repo: Repo, name: str = "service") -> None:
                self.repo = repo
                self.name = name

        service = container.resolve(Service)

        assert service.name == "service"
        assert service.repo.name == "repo"

    async def test_resolve_with_defaults_async_resolver(
        self,
        container: Container,
    ) -> None:
        @singleton
        class Repo:
            def __init__(self, name: str = "repo") -> None:
                self.name = name

        @singleton
        class Service:
            def __init__(self, repo: Repo, name: str = "service") -> None:
                self.repo = repo
                self.name = name

        service = await container.aresolve(Service)

        assert service.name == "service"
        assert service.repo.name == "repo"

    def test_is_resolved(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def message() -> str:
            return "test"

        _ = container.resolve(str)

        assert container.is_resolved(str)

    def test_is_resolved_transient(self, container: Container) -> None:
        @container.provider(scope="transient")
        def message() -> str:
            return "test"

        _ = container.resolve(str)

        assert not container.is_resolved(str)

    def test_is_not_resolved(self, container: Container) -> None:
        assert not container.is_resolved(str)

    def test_release_instance(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="singleton")
        container.resolve(str)

        assert container.is_resolved(str)

        container.release(str)

        assert not container.is_resolved(str)

    def test_release_transient_instance(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="transient")

        assert not container.is_resolved(str)

        container.release(str)

        assert not container.is_resolved(str)

    def test_on_the_fly_resolution_with_circular_dependency(self) -> None:
        """Test circular dependency detection during on-the-fly resolution."""

        @singleton
        class ServiceA:
            pass

        @singleton
        class ServiceB:
            pass

        container = Container()

        @container.provider(scope="singleton")
        def provide_a(b: ServiceB) -> ServiceA:
            return ServiceA()

        @container.provider(scope="singleton")
        def provide_b(a: ServiceA) -> ServiceB:
            return ServiceB()

        # Don't call build() - try to resolve on-the-fly
        # This should detect circular dependency
        with pytest.raises(ValueError, match="Circular dependency detected"):
            container.resolve(ServiceA)

    def test_on_the_fly_resolution_scope_incompatibility(self) -> None:
        """Test scope validation during on-the-fly resolution."""
        container = Container()

        @singleton
        class RequestDep:
            pass

        @request
        class SingletonService:
            pass

        @container.provider(scope="singleton")
        def provide_singleton(dep: RequestDep) -> SingletonService:
            return SingletonService()

        container.register(RequestDep, scope="request")

        # Try to resolve without build - should detect scope incompatibility
        with pytest.raises(
            ValueError,
            match=r"cannot depend on.*with a.*scope",
        ):
            container.resolve(SingletonService)

    def test_on_the_fly_already_resolved_parameters(self) -> None:
        """Test skipping already resolved parameters during on-the-fly resolution."""
        container = Container()

        @singleton
        class DepA:
            pass

        @singleton
        class DepB:
            pass

        @singleton
        class Service:
            pass

        # Register providers with dependencies
        @container.provider(scope="singleton")
        def provide_service(a: DepA, b: DepB) -> Service:
            return Service()

        container.register(DepA)
        container.register(DepB)

        # Resolve without build() - will resolve on-the-fly
        # This hits the already-resolved check in _ensure_provider_resolved
        service = container.resolve(Service)
        assert isinstance(service, Service)

    def test_circular_dependency_self_reference(self) -> None:
        """Test circular dependency where provider references itself."""
        container = Container()

        @singleton
        class SelfRef:
            pass

        # Create a self-referencing provider
        @container.provider(scope="singleton")
        def provide_self_ref(self_dep: SelfRef) -> SelfRef:
            return SelfRef()

        # Try to resolve - should detect circular dependency
        # This hits line 558 (early return when already in resolving set)
        with pytest.raises(ValueError, match="Circular dependency"):
            container.resolve(SelfRef)


class TestContainerCreate:
    """Tests for container Create functionality."""

    def test_create_transient(self) -> None:
        @transient
        class Component:
            def __init__(self, name: str) -> None:
                self.name = name

        container = Container()

        instance = container.create(Component, name="test")

        assert instance.name == "test"

    def test_create_singleton(self) -> None:
        @singleton
        class Component:
            def __init__(self, name: str) -> None:
                self.name = name

        container = Container()

        instance = container.create(Component, name="test")

        assert instance.name == "test"

    def test_create_scoped(self) -> None:
        @request
        class Component:
            def __init__(self, name: str) -> None:
                self.name = name

        container = Container()

        with container.request_context():
            instance = container.create(Component, name="test")

        assert instance.name == "test"

    def test_create_non_existing_keyword_arg(self) -> None:
        @singleton
        class Component:
            pass

        container = Container()

        with pytest.raises(TypeError, match="takes no arguments"):
            container.create(Component, param="test")

    async def test_create_async_transient(self) -> None:
        @transient
        class Component:
            def __init__(self, name: str) -> None:
                self.name = name

        container = Container()

        instance = await container.acreate(Component, name="test")

        assert instance.name == "test"

    async def test_create_async_singleton(self) -> None:
        @singleton
        class Component:
            def __init__(self, name: str) -> None:
                self.name = name

        container = Container()

        instance = await container.acreate(Component, name="test")

        assert instance.name == "test"

    async def test_create_async_scoped(self) -> None:
        @request
        class Component:
            def __init__(self, name: str) -> None:
                self.name = name

        container = Container()

        with container.request_context():
            instance = await container.acreate(Component, name="test")

        assert instance.name == "test"

    async def test_create_async_non_existing_keyword_arg(self) -> None:
        @singleton
        class Component:
            pass

        container = Container()

        with pytest.raises(TypeError, match="takes no arguments"):
            await container.acreate(Component, param="test")

    async def test_create_async_function_with_defaults(self) -> None:
        """Test async function provider with parameters and defaults."""

        @singleton
        class Database:
            def __init__(self) -> None:
                self.name = "db"

        container = Container()

        @container.provider(scope="singleton")
        async def create_service(
            db: Database, timeout: int = 30, retries: int = 3
        ) -> str:
            return f"Service(db={db.name}, timeout={timeout}, retries={retries})"

        # Create with custom defaults overriding the function defaults
        result = await container.acreate(str, timeout=60, retries=5)

        assert result == "Service(db=db, timeout=60, retries=5)"

    def test_create_without_defaults(self) -> None:
        """Test create without passing any defaults."""

        @singleton
        class Database:
            def __init__(self) -> None:
                self.name = "db"

        @transient
        class Service:
            def __init__(self, db: Database) -> None:
                self.db = db

        container = Container()

        # Create without any defaults - should use cached resolver
        instance1 = container.create(Service)
        instance2 = container.create(Service)

        assert instance1.db.name == "db"
        assert instance2.db.name == "db"

        # Transient scope should create new instances
        assert instance1 is not instance2
        # But singleton dependency should be the same
        assert instance1.db is instance2.db

    async def test_create_async_without_defaults(self) -> None:
        """Test acreate without passing any defaults."""

        @singleton
        class Database:
            def __init__(self) -> None:
                self.name = "db"

        @transient
        class Service:
            def __init__(self, db: Database) -> None:
                self.db = db

        container = Container()

        # Create without any defaults - should use cached resolver
        instance1 = await container.acreate(Service)
        instance2 = await container.acreate(Service)

        assert instance1.db.name == "db"
        assert instance2.db.name == "db"

        # Transient scope should create new instances
        assert instance1 is not instance2
        # But singleton dependency should be the same
        assert instance1.db is instance2.db


class TestContainerContext:
    """Tests for container Context functionality."""

    def test_start_and_close_singleton_context(self, container: Container) -> None:
        events = []

        def dep1() -> Iterator[str]:
            events.append("dep1:before")
            yield "test"
            events.append("dep1:after")

        container.register(str, dep1, scope="singleton")

        container.start()

        assert container.resolve(str) == "test"

        container.close()

        assert events == ["dep1:before", "dep1:after"]

    def test_request_context(self, container: Container) -> None:
        events = []

        def dep1() -> Iterator[str]:
            events.append("dep1:before")
            yield "test"
            events.append("dep1:after")

        container.register(str, dep1, scope="request")

        with container.request_context():
            assert container.resolve(str) == "test"

        assert events == ["dep1:before", "dep1:after"]

    # Asynchronous lifespan

    async def test_astart_and_aclose_singleton_context(
        self, container: Container
    ) -> None:
        events = []

        async def dep1() -> AsyncIterator[str]:
            events.append("dep1:before")
            yield "test"
            events.append("dep1:after")

        container.register(str, dep1, scope="singleton")

        await container.astart()

        assert container.resolve(str) == "test"

        await container.aclose()

        assert events == ["dep1:before", "dep1:after"]

    async def test_arequest_context(self, container: Container) -> None:
        events = []

        async def dep1() -> AsyncIterator[str]:
            events.append("dep1:before")
            yield "test"
            events.append("dep1:after")

        container.register(str, dep1, scope="request")

        async with container.arequest_context():
            assert await container.aresolve(str) == "test"

        assert events == ["dep1:before", "dep1:after"]

    def test_reset_resolved_instances(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="singleton")
        container.register(int, lambda: 1, scope="singleton")

        container.resolve(str)
        container.resolve(int)

        assert container.is_resolved(str)
        assert container.is_resolved(int)

        container.reset()

        assert not container.is_resolved(str)
        assert not container.is_resolved(int)

    def test_reset_transient(self, container: Container) -> None:
        container.register(str, lambda: "test", scope="transient")

        _ = container.resolve(str)

        assert not container.is_resolved(str)

        container.reset()

        assert not container.is_resolved(str)

    # Instance

    def test_get_scoped_context_success(self) -> None:
        @request
        class RequestService:
            pass

        container = Container()

        with container.request_context() as ctx:
            retrieved_ctx = container._get_scoped_context("request")
            assert retrieved_ctx is ctx

    def test_reset_with_lookup_error(self) -> None:
        container = Container()

        container.register_scope("custom")

        @provided(scope="custom")
        class CustomService:
            pass

        container.register(CustomService, scope="custom")

        container.reset()

    def test_scoped_with_defaults_override(self, container: Container) -> None:
        container.register(int, lambda: 1, scope="request")

        with container.request_context():
            assert container.create(int) == 1

    def test_register_deprecated_interface(self, container: Container) -> None:
        with pytest.warns(
            DeprecationWarning,
            match="The `interface` is deprecated. Use `dependency_type` instead.",
        ):
            container.register(interface=int, factory=lambda: 42)

        assert container.resolve(int) == 42

    def test_register_deprecated_call(self, container: Container) -> None:
        with pytest.warns(
            DeprecationWarning,
            match="The `call` is deprecated. Use `factory` instead.",
        ):
            container.register(int, call=lambda: 42)

        assert container.resolve(int) == 42

    def test_register_deprecated_both(self, container: Container) -> None:
        with pytest.warns(DeprecationWarning, match="is deprecated"):
            container.register(interface=int, call=lambda: 42)

        assert container.resolve(int) == 42

    def test_get_context_scopes_with_resources(self) -> None:
        """Test get_context_scopes includes scopes with resource providers."""
        container = Container()

        # Register custom scope with resource provider
        container.register_scope("task", parents=["singleton"])

        @container.provider(scope="task")
        def task_resource() -> Iterator[str]:
            yield "task_value"

        # Call with specific scopes to trigger the helper function
        # This will add task and its parent singleton
        scopes = container.get_context_scopes(scopes={"task"})

        # Should include task and its parents
        assert "singleton" in scopes
        assert "task" in scopes

        # Test that scopes with resources are included
        scopes2 = container.get_context_scopes(scopes={"singleton"})
        # Should include task because it has a resource
        assert "task" in scopes2


class TestContainerLifecycle:
    """Tests for container Lifecycle functionality."""

    def test_resource_delegated_exception(self, container: Container) -> None:
        resource = Resource()

        @container.provider(scope="request")
        def resource_provider() -> Iterator[Resource]:
            try:
                yield resource
            except Exception:
                resource.rollback()
                raise
            else:
                resource.commit()

        def _resolve() -> None:
            resource = container.resolve(Resource)
            resource.run()
            raise ValueError("error")

        with pytest.raises(ValueError, match="error"), container.request_context():
            _resolve()

        assert resource.called
        assert not resource.committed
        assert resource.rolled_back

    async def test_async_resource_delegated_exception(
        self, container: Container
    ) -> None:
        resource = Resource()

        @container.provider(scope="request")
        async def resource_provider() -> AsyncIterator[Resource]:
            try:
                yield resource
            except Exception:
                resource.rollback()
                raise
            else:
                resource.commit()

        async def _resolve() -> None:
            resource = await container.aresolve(Resource)
            resource.run()
            raise ValueError("error")

        with pytest.raises(ValueError, match="error"):
            async with container.arequest_context():
                await _resolve()

        assert resource.called
        assert not resource.committed
        assert resource.rolled_back

    # Inspections


class TestContainerUtilities:
    """Tests for container Utilities functionality."""

    def test_container_available_as_dependency(self, container: Container) -> None:
        assert container.has_provider_for(Container)
        assert container.resolve(Container) is container

        @container.inject
        def dependent(current: Container = Inject()) -> Container:
            return current

        assert dependent() is container

    def test_logger_property(self) -> None:
        custom_logger = logging.getLogger("custom")
        container = Container(logger=custom_logger)

        assert container.logger is custom_logger

    def test_has_scope(self) -> None:
        """Test has_scope() method."""
        container = Container()
        assert container.has_scope("singleton")
        assert container.has_scope("transient")
        assert container.has_scope("request")
        assert not container.has_scope("nonexistent")

        container.register_scope("custom")
        assert container.has_scope("custom")

    def test_scan_packages(self) -> None:
        """Test scanning packages for providers."""
        container = Container()

        # Scan just the decorators module which has no external dependencies
        container.scan("anydi._decorators")

        # After scanning, container should work
        assert container is not None

    def test_inject_decorator_without_arguments(self) -> None:
        """Test using @container.inject without parentheses."""
        container = Container()

        @singleton
        class Service:
            value = "test"

        container.register(Service)

        @container.inject
        def func(service: Service = Inject()) -> str:
            return service.value

        result = func()
        assert result == "test"

    def test_inject_decorator_with_parentheses(self) -> None:
        """Test using @container.inject() with parentheses."""
        container = Container()

        @singleton
        class Service:
            value = "test"

        container.register(Service)

        @container.inject()
        def func(service: Service = Inject()) -> str:
            return service.value

        result = func()
        assert result == "test"

    def test_validate_injected_parameter(self) -> None:
        """Test validate_injected_parameter() method."""
        container = Container()

        @singleton
        class Service:
            pass

        container.register(Service)

        def example_func(service: Service = Inject()) -> None:
            pass

        sig = inspect.signature(example_func)
        param = sig.parameters["service"]
        annotation, has_marker, marker = container.validate_injected_parameter(
            param, call=example_func
        )
        assert annotation is Service
        assert has_marker is True
        assert marker is not None


class TestContainerCustomScopes:
    """Tests for custom scope registration and resolution."""

    def test_register_custom_scope(self, container: Container) -> None:
        """Test registering a custom scope with parent scopes."""
        container.register_scope("task", parents=["singleton"])

        assert "task" in container._scopes
        assert "task" in container._scopes["task"]
        assert "singleton" in container._scopes["task"]

    def test_register_custom_scope_with_multiple_parents(
        self, container: Container
    ) -> None:
        """Test registering a custom scope with multiple parent scopes."""
        container.register_scope("task", parents=["singleton"])
        container.register_scope("workflow", parents=["task"])

        assert "workflow" in container._scopes
        assert "workflow" in container._scopes["workflow"]
        assert "singleton" in container._scopes["workflow"]
        assert "task" in container._scopes["workflow"]

    def test_register_custom_scope_no_parents(self, container: Container) -> None:
        """Test registering a custom scope without parent scopes."""
        container.register_scope("session")

        assert "session" in container._scopes
        assert "session" in container._scopes["session"]
        assert "singleton" in container._scopes["session"]

    def test_register_custom_scope_already_registered(
        self, container: Container
    ) -> None:
        """Test registering an already registered custom scope raises error."""
        container.register_scope("task")

        with pytest.raises(
            ValueError,
            match=r"The scope `task` is already registered.",
        ):
            container.register_scope("task")

    def test_register_reserved_scope_singleton(self, container: Container) -> None:
        """Test registering a reserved scope 'singleton' raises error."""
        with pytest.raises(
            ValueError,
            match=r"The scope `singleton` is reserved and cannot be overridden.",
        ):
            container.register_scope("singleton")

    def test_register_reserved_scope_transient(self, container: Container) -> None:
        """Test registering a reserved scope 'transient' raises error."""
        with pytest.raises(
            ValueError,
            match=r"The scope `transient` is reserved and cannot be overridden.",
        ):
            container.register_scope("transient")

    def test_register_custom_scope_with_nonexistent_parent(
        self, container: Container
    ) -> None:
        """Test registering a custom scope with non-existent parent raises error."""
        with pytest.raises(
            ValueError,
            match=r"The parent scope `nonexistent` is not registered.",
        ):
            container.register_scope("task", parents=["nonexistent"])

    def test_resolve_custom_scoped(self, container: Container) -> None:
        """Test resolving a provider with custom scope."""
        instance = "task_value"

        container.register_scope("task")
        container.register(str, lambda: instance, scope="task")

        with container.scoped_context("task"):
            assert container.resolve(str) == instance

    def test_resolve_custom_scoped_not_started(self, container: Container) -> None:
        """Test resolving custom scope without context raises error."""
        container.register_scope("task")
        container.register(str, lambda: "test", scope="task")

        with pytest.raises(
            LookupError,
            match=(
                r"The task context has not been started. "
                "Please ensure that the task context is properly initialized "
                "before attempting to use it."
            ),
        ):
            container.resolve(str)

    def test_resolve_custom_scope_with_singleton_dependency(
        self, container: Container
    ) -> None:
        """Test resolving custom scope provider that depends on singleton."""
        container.register_scope("task")

        def singleton_dep() -> int:
            return 42

        def task_dep(x: int) -> str:
            return f"value: {x}"

        container.register(int, singleton_dep, scope="singleton")
        container.register(str, task_dep, scope="task")

        with container:
            with container.scoped_context("task"):
                result = container.resolve(str)
                assert result == "value: 42"

    def test_resolve_custom_scope_with_parent_dependency(
        self, container: Container
    ) -> None:
        """Test resolving custom scope provider that depends on parent scope."""
        container.register_scope("task", parents=["singleton"])
        container.register_scope("workflow", parents=["task"])

        def singleton_dep() -> int:
            return 10

        def task_dep(x: int) -> float:
            return x * 2.5

        def workflow_dep(y: float) -> str:
            return f"result: {y}"

        container.register(int, singleton_dep, scope="singleton")
        container.register(float, task_dep, scope="task")
        container.register(str, workflow_dep, scope="workflow")

        with container:
            with container.scoped_context("task"):
                with container.scoped_context("workflow"):
                    result = container.resolve(str)
                    assert result == "result: 25.0"

    def test_resolve_custom_scope_instance_caching(self, container: Container) -> None:
        """Test that instances are cached within custom scope context."""
        container.register_scope("task")
        container.register(UniqueId, scope="task")

        with container.scoped_context("task"):
            instance1 = container.resolve(UniqueId)
            instance2 = container.resolve(UniqueId)
            assert instance1 is instance2

    def test_resolve_custom_scope_isolation(self, container: Container) -> None:
        """Test that custom scope instances are isolated across contexts."""
        container.register_scope("task")
        container.register(UniqueId, scope="task")

        with container.scoped_context("task"):
            instance1 = container.resolve(UniqueId)

        with container.scoped_context("task"):
            instance2 = container.resolve(UniqueId)

        assert instance1 is not instance2

    def test_resolve_custom_scope_with_resource(self, container: Container) -> None:
        """Test resolving custom scope with resource provider."""
        container.register_scope("task")

        @container.provider(scope="task")
        def provide() -> Iterator[str]:
            yield "resource_value"

        with container.scoped_context("task"):
            result = container.resolve(str)
            assert result == "resource_value"

    async def test_resolve_custom_scope_async(self, container: Container) -> None:
        """Test async resolution with custom scope."""
        container.register_scope("task")

        async def async_provider() -> str:
            return "async_value"

        container.register(str, async_provider, scope="task")

        async with container.ascoped_context("task"):
            result = await container.aresolve(str)
            assert result == "async_value"

    async def test_resolve_custom_scope_async_resource(
        self, container: Container
    ) -> None:
        """Test async resolution with custom scope async resource."""
        container.register_scope("task")

        @container.provider(scope="task")
        async def provide() -> AsyncIterator[str]:
            yield "async_resource"

        async with container.ascoped_context("task"):
            result = await container.aresolve(str)
            assert result == "async_resource"

    def test_resolve_custom_scope_thread_safe(self, container: Container) -> None:
        """Test that custom scope resolution is thread-safe."""
        container.register_scope("task")
        container.register(UniqueId, scope="task")

        results: list[tuple[UniqueId, UniqueId]] = []

        def worker() -> None:
            with container.scoped_context("task"):
                id1 = container.resolve(UniqueId)
                id2 = container.resolve(UniqueId)
                results.append((id1, id2))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Each thread should get the same instance within its context
        for id1, id2 in results:
            assert id1 is id2

        # But different threads should get different instances
        unique_ids = {id(pair[0]) for pair in results}
        assert len(unique_ids) == 5

    def test_custom_scope_dependency_validation(self, container: Container) -> None:
        """Test that custom scope cannot depend on disallowed scopes."""
        container.register_scope("task", parents=["singleton"])

        def transient_dep() -> int:
            return 42

        def task_dep(x: int) -> str:
            return f"value: {x}"

        container.register(int, transient_dep, scope="transient")
        container.register(str, task_dep, scope="task")

        with pytest.raises(
            ValueError,
            match=(
                r"The provider .* with a `task` scope "
                r"cannot depend on .* with a `transient` scope"
            ),
        ):
            container.build()

    def test_custom_scope_allows_transient_dependencies_from_transient(
        self, container: Container
    ) -> None:
        """Test that transient scope can depend on custom scopes."""
        container.register_scope("task")

        def task_dep() -> int:
            return 42

        def transient_dep(x: int) -> str:
            return f"value: {x}"

        container.register(int, task_dep, scope="task")
        container.register(str, transient_dep, scope="transient")

        with container.scoped_context("task"):
            result = container.resolve(str)
            assert result == "value: 42"

    def test_custom_scope_multiple_providers(self, container: Container) -> None:
        """Test multiple providers registered with custom scope."""
        container.register_scope("task")

        container.register(int, lambda: 10, scope="task")
        container.register(str, lambda: "test", scope="task")
        container.register(float, lambda: 3.14, scope="task")

        with container.scoped_context("task"):
            assert container.resolve(int) == 10
            assert container.resolve(str) == "test"
            assert container.resolve(float) == 3.14

    def test_custom_scope_auto_nested_dependencies(self, container: Container) -> None:
        container.register_scope("task")

        @provided(scope="task")
        class Repository:
            pass

        @provided(scope="task")
        class Service:
            def __init__(self, repository: Repository) -> None:
                self.repository = repository

        with container.scoped_context("task"):
            result = container.resolve(Service)

        assert isinstance(result, Service)
        assert isinstance(result.repository, Repository)

    async def test_custom_scope_auto_nested_dependencies_async(
        self, container: Container
    ) -> None:
        container.register_scope("task")

        @provided(scope="task")
        class Repository:
            pass

        @provided(scope="task")
        class Service:
            def __init__(self, repository: Repository) -> None:
                self.repository = repository

        async with container.ascoped_context("task"):
            result = await container.aresolve(Service)

        assert isinstance(result, Service)
        assert isinstance(result.repository, Repository)

    def test_custom_scope_from_context_not_set(self, container: Container) -> None:
        container.register_scope("task")

        class TaskRequest:
            def __init__(self, task_id: str) -> None:
                self.task_id = task_id

        container.register(TaskRequest, scope="task", from_context=True)

        @container.provider(scope="task")
        def task_handler(req: TaskRequest) -> str:
            return req.task_id

        with (
            pytest.raises(
                LookupError,
                match=(
                    r"The provider `.*TaskRequest` is registered with "
                    r"from_context=True but has not been set in the task context."
                ),
            ),
            container.scoped_context("task"),
        ):
            container.resolve(str)

    def test_custom_scope_from_context_success(self, container: Container) -> None:
        container.register_scope("task")

        class TaskRequest:
            def __init__(self, task_id: str) -> None:
                self.task_id = task_id

        container.register(TaskRequest, scope="task", from_context=True)

        @container.provider(scope="task")
        def task_handler(req: TaskRequest) -> str:
            return req.task_id

        with container.scoped_context("task") as context:
            context.set(TaskRequest, TaskRequest(task_id="task-123"))
            assert container.resolve(str) == "task-123"

    def test_custom_scope_nested_parent_scope_dependency(
        self, container: Container
    ) -> None:
        container.register_scope("task", parents=["request"])

        @request
        class RequestContext:
            pass

        @provided(scope="task")
        class TaskHandler:
            def __init__(self, ctx: RequestContext) -> None:
                self.ctx = ctx

        with container.request_context():
            with container.scoped_context("task"):
                result = container.resolve(TaskHandler)

        assert isinstance(result, TaskHandler)
        assert isinstance(result.ctx, RequestContext)

    async def test_custom_scope_nested_parent_scope_dependency_async(
        self, container: Container
    ) -> None:
        container.register_scope("task", parents=["request"])

        @request
        class RequestContext:
            pass

        @provided(scope="task")
        class TaskHandler:
            def __init__(self, ctx: RequestContext) -> None:
                self.ctx = ctx

        async with container.arequest_context():
            async with container.ascoped_context("task"):
                result = await container.aresolve(TaskHandler)

        assert isinstance(result, TaskHandler)
        assert isinstance(result.ctx, RequestContext)

    def test_unregister_custom_scoped_provider(self, container: Container) -> None:
        """Test unregistering a provider with custom scope."""
        container.register_scope("task")
        container.register(str, lambda: "test", scope="task")

        with container.scoped_context("task"):
            container.resolve(str)

        container.unregister(str)

        assert not container.is_registered(str)

    def test_get_scoped_context_var_for_reserved_scope_singleton(
        self, container: Container
    ) -> None:
        """Test that getting context var for singleton scope raises error."""
        with pytest.raises(
            ValueError,
            match=r"Cannot get context variable for reserved scope `singleton`.",
        ):
            container._get_scoped_context_var("singleton")

    def test_get_scoped_context_var_for_reserved_scope_transient(
        self, container: Container
    ) -> None:
        """Test that getting context var for transient scope raises error."""
        with pytest.raises(
            ValueError,
            match=r"Cannot get context variable for reserved scope `transient`.",
        ):
            container._get_scoped_context_var("transient")

    def test_get_scoped_context_var_for_not_registered_scope(
        self, container: Container
    ) -> None:
        """Test that getting context var for unregistered scope raises error."""
        with pytest.raises(
            ValueError,
            match=(
                r"Cannot get context variable for not registered scope `unregistered`. "
                "Please register the scope first using register_scope()."
            ),
        ):
            container._get_scoped_context_var("unregistered")

    def test_scoped_context_with_reserved_scope_singleton(
        self, container: Container
    ) -> None:
        """Test that scoped_context with singleton scope raises error."""
        with pytest.raises(
            ValueError,
            match=r"Cannot get context variable for reserved scope `singleton`.",
        ):
            with container.scoped_context("singleton"):
                pass

    def test_scoped_context_with_reserved_scope_transient(
        self, container: Container
    ) -> None:
        """Test that scoped_context with transient scope raises error."""
        with pytest.raises(
            ValueError,
            match=r"Cannot get context variable for reserved scope `transient`.",
        ):
            with container.scoped_context("transient"):
                pass

    def test_scoped_context_with_not_registered_scope(
        self, container: Container
    ) -> None:
        """Test that scoped_context with unregistered scope raises error."""
        with pytest.raises(
            ValueError,
            match=(
                r"Cannot get context variable for not registered scope `unknown`. "
                "Please register the scope first using register_scope()."
            ),
        ):
            with container.scoped_context("unknown"):
                pass

    async def test_ascoped_context_with_reserved_scope_singleton(
        self, container: Container
    ) -> None:
        """Test that ascoped_context with singleton scope raises error."""
        with pytest.raises(
            ValueError,
            match=r"Cannot get context variable for reserved scope `singleton`.",
        ):
            async with container.ascoped_context("singleton"):
                pass

    async def test_ascoped_context_with_reserved_scope_transient(
        self, container: Container
    ) -> None:
        """Test that ascoped_context with transient scope raises error."""
        with pytest.raises(
            ValueError,
            match=r"Cannot get context variable for reserved scope `transient`.",
        ):
            async with container.ascoped_context("transient"):
                pass

    async def test_ascoped_context_with_not_registered_scope(
        self, container: Container
    ) -> None:
        """Test that ascoped_context with unregistered scope raises error."""
        with pytest.raises(
            ValueError,
            match=(
                r"Cannot get context variable for not registered scope `unknown`. "
                "Please register the scope first using register_scope()."
            ),
        ):
            async with container.ascoped_context("unknown"):
                pass

    def test_scoped_context_reentry_same_scope(self, container: Container) -> None:
        """Test that re-entering the same scoped context reuses existing context."""
        container.register_scope("task")
        container.register(UniqueId, scope="task")  # type: ignore[arg-type]

        with container.scoped_context("task") as ctx1:
            instance1 = container.resolve(UniqueId)

            # Re-enter the same scope
            with container.scoped_context("task") as ctx2:
                instance2 = container.resolve(UniqueId)

                # Should be the same context
                assert ctx1 is ctx2
                # Should be the same instance
                assert instance1 is instance2

    async def test_ascoped_context_reentry_same_scope(
        self, container: Container
    ) -> None:
        """Test re-entering same async scoped context reuses existing context."""
        container.register_scope("task")
        container.register(UniqueId, scope="task")  # type: ignore[arg-type]

        async with container.ascoped_context("task") as ctx1:
            instance1 = await container.aresolve(UniqueId)

            # Re-enter the same scope
            async with container.ascoped_context("task") as ctx2:
                instance2 = await container.aresolve(UniqueId)

                # Should be the same context
                assert ctx1 is ctx2
                # Should be the same instance
                assert instance1 is instance2

    def test_singleton_context_reentry(self, container: Container) -> None:
        """Test that re-entering the singleton context works correctly."""
        container.register(UniqueId, scope="singleton")

        with container:
            instance1 = container.resolve(UniqueId)

            # Re-enter the singleton context
            with container:
                instance2 = container.resolve(UniqueId)

                # Should be the same instance
                assert instance1 is instance2

    async def test_singleton_context_async_reentry(self, container: Container) -> None:
        """Test that re-entering the async singleton context works correctly."""
        container.register(UniqueId, scope="singleton")

        async with container:
            instance1 = await container.aresolve(UniqueId)

            # Re-enter the singleton context
            async with container:
                instance2 = await container.aresolve(UniqueId)

                # Should be the same instance
                assert instance1 is instance2

    def test_request_context_reentry(self, container: Container) -> None:
        """Test that re-entering the request context reuses existing context."""
        container.register(UniqueId, scope="request")

        with container.request_context() as ctx1:
            instance1 = container.resolve(UniqueId)

            # Re-enter the request context
            with container.request_context() as ctx2:
                instance2 = container.resolve(UniqueId)

                # Should be the same context (request_context calls scoped_context)
                assert ctx1 is ctx2
                # Should be the same instance
                assert instance1 is instance2

    def test_get_context_scopes_default(self, container: Container) -> None:
        """Test get_context_scopes with default scopes."""
        # Default context scopes: singleton and request
        ordered = container.get_context_scopes()

        assert ordered == ["singleton", "request"]

    def test_get_context_scopes_with_custom_scopes(self, container: Container) -> None:
        """Test get_context_scopes with custom scopes."""
        # Register custom scopes
        container.register_scope("batch")
        container.register_scope("session")

        ordered = container.get_context_scopes()

        # Should have singleton, request, then custom scopes
        assert ordered[0] == "singleton"
        assert ordered[1] == "request"
        # batch and session should be after request
        assert "batch" in ordered
        assert "session" in ordered

    def test_get_context_scopes_with_nested_scopes(self, container: Container) -> None:
        """Test get_context_scopes with nested scope hierarchies."""
        # Register nested scopes: tenant -> request
        container.register_scope("tenant", parents=["request"])
        container.register_scope("organization", parents=["tenant"])

        ordered = container.get_context_scopes()

        # Should be: singleton, request, tenant, organization
        assert ordered == [
            "singleton",
            "request",
            "tenant",
            "organization",
        ]

    def test_get_context_scopes_respects_dependency_order(
        self, container: Container
    ) -> None:
        """Test that get_context_scopes respects dependency order."""
        # Create a complex hierarchy
        container.register_scope("level1")
        container.register_scope("level2", parents=["level1"])
        container.register_scope("level3", parents=["level2"])

        ordered = container.get_context_scopes()

        # Should be ordered by depth: singleton, request, custom by depth
        assert ordered[0] == "singleton"
        assert ordered[1] == "request"
        # level1 has 2 items (itself + singleton), level2 has 3, level3 has 4
        assert ordered.index("level1") < ordered.index("level2")
        assert ordered.index("level2") < ordered.index("level3")


class TestContainerInjector:
    def test_inject_using_inject_marker(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def message() -> str:
            return "test"

        @container.inject
        def func(message: str = Inject()) -> str:
            return message

        result = func()

        assert result == "test"

    def test_inject_using_provide_annotation(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def message() -> str:
            return "test"

        @container.inject
        def func(message: Provide[str]) -> str:
            return message

        result = container.run(func)

        assert result == "test"

    def test_inject_using_inject_annotated_marker(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def message() -> str:
            return "test"

        @container.inject
        def func(message: Annotated[str, Inject()]) -> str:
            return message

        result = func()  # type: ignore

        assert result == "test"

    def test_inject_using_inject_annotated_with_marker(
        self, container: Container
    ) -> None:
        @container.provider(scope="singleton")
        def message() -> str:
            return "test"

        with pytest.raises(
            TypeError,
            match=(
                "Cannot specify `Inject` in `Annotated` and default value "
                "together for 'message'"
            ),
        ):

            @container.inject
            def func(message: Annotated[str, Inject()] = Inject()) -> str:
                return message

    def test_inject_missing_annotation(self, container: Container) -> None:
        def handler(name=Inject()) -> str:  # type: ignore
            return name  # type: ignore

        with pytest.raises(
            TypeError, match=r"Missing `(.*?).handler` parameter `name` annotation."
        ):
            container.inject(handler)

    def test_inject_unknown_dependency(self) -> None:
        container = Container()

        def handler(message: str = Inject()) -> None:
            pass

        with pytest.raises(
            LookupError,
            match=(
                r"`(.*?).handler` has an unknown dependency parameter `message` "
                "with an annotation of `str`."
            ),
        ):
            container.inject(handler)

    def test_inject_class(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def ident_provider() -> str:
            return "1000"

        @container.provider(scope="singleton")
        def service_provider(ident: str) -> Service:
            return Service(ident=ident)

        @container.inject
        class Handler:
            def __init__(self, name: str, service: Service = Inject()) -> None:
                self.name = name
                self.service = service

            def handle(self) -> str:
                return f"{self.name} = {self.service.ident}"

        handler = Handler(name="service ident")

        result = handler.handle()

        assert result == "service ident = 1000"

    async def test_inject_with_sync_and_async_resources(
        self, container: Container
    ) -> None:
        def ident_provider() -> Iterator[str]:
            yield "1000"

        async def service_provider(ident: str) -> AsyncIterator[Service]:
            yield Service(ident=ident)

        container.register(str, ident_provider, scope="singleton")
        container.register(Service, service_provider, scope="singleton")

        await container.astart()

        @container.inject
        async def func(name: str, service: Service = Inject()) -> str:
            return f"{name} = {service.ident}"

        result = await func(name="service ident")

        assert result == "service ident = 1000"

    def test_run(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def value1() -> Annotated[int, "value1"]:
            return 10

        @container.provider(scope="singleton")
        def value2() -> Annotated[int, "value2"]:
            return 20

        def sum_handler(
            value1: int,
            value2: Annotated[int, "value1"] = Inject(),
            value3: Annotated[int, "value2"] = Inject(),
        ) -> int:
            return value1 + value2 + value3

        result = container.run(sum_handler, value1=30)

        assert result == 60

    def test_run_cached(self, container: Container) -> None:
        @container.provider(scope="singleton")
        def message() -> str:
            return "hello"

        def handler(message: str = Inject()) -> str:
            return message

        _ = container.run(handler)
        _ = container.run(handler)

        assert handler in container._injector._cache

    def test_inject_with_annotated_and_default(self) -> None:
        container = Container()

        @container.provider(scope="singleton")
        def value() -> int:
            return 42

        def handler(x: Annotated[int, Inject()] = 10) -> int:
            return x

        injected = container.inject(handler)
        result = injected()

        assert result == 10


class TestContainerOverride:
    def test_override_instance(self) -> None:
        origin_name = "origin"
        overridden_name = "overridden"

        container = Container()
        container.enable_test_mode()

        @container.provider(scope="singleton")
        def name() -> str:
            return origin_name

        with container.override(str, overridden_name):
            assert container.resolve(str) == overridden_name

        assert container.resolve(str) == origin_name

    def test_override_without_test_mode_warning(self) -> None:
        """Test that override() without test mode triggers a warning."""
        container = Container()
        container.register(str, lambda: "original")

        with pytest.warns(
            UserWarning, match=r"Using override\(\) without enabling test mode"
        ):
            with container.override(str, "overridden"):
                assert container.resolve(str) == "overridden"

        assert container.resolve(str) == "original"

    def test_override_instance_provider_not_registered_using_strict_mode(self) -> None:
        container = Container()
        container.enable_test_mode()

        with pytest.raises(LookupError, match=r"The provider `str` is not registered."):
            with container.override(str, "test"):
                pass

    def test_override_instance_transient_provider(self) -> None:
        overridden_uuid = uuid.uuid4()

        container = Container()
        container.enable_test_mode()

        @container.provider(scope="transient")
        def uuid_provider() -> uuid.UUID:
            return uuid.uuid4()

        with container.override(uuid.UUID, overridden_uuid):
            assert container.resolve(uuid.UUID) == overridden_uuid

        assert container.resolve(uuid.UUID) != overridden_uuid

    def test_override_instance_resource_provider(self) -> None:
        origin = "origin"
        overridden = "overridden"

        container = Container()
        container.enable_test_mode()

        @container.provider(scope="singleton")
        def message() -> Iterator[str]:
            yield origin

        with container.override(str, overridden):
            assert container.resolve(str) == overridden

        assert container.resolve(str) == origin

    async def test_override_instance_async_resource_provider(self) -> None:
        origin = "origin"
        overridden = "overridden"

        container = Container()
        container.enable_test_mode()

        @container.provider(scope="singleton")
        async def message() -> AsyncIterator[str]:
            yield origin

        with container.override(str, overridden):
            assert (await container.aresolve(str)) == overridden

    def test_override_registered_instance(self) -> None:
        container = Container()
        container.enable_test_mode()
        container.register(Annotated[str, "param"], lambda: "param", scope="singleton")

        @singleton
        class UserRepo:
            def get_user(self) -> str:
                return "user"

        @singleton
        class UserService:
            def __init__(self, repo: UserRepo, param: Annotated[str, "param"]) -> None:
                self.repo = repo
                self.param = param

            def process(self) -> dict[str, str]:
                return {
                    "user": self.repo.get_user(),
                    "param": self.param,
                }

        user_repo_mock = mock.MagicMock(spec=UserRepo)
        user_repo_mock.get_user.return_value = "mocked_user"

        # Set up overrides first, then resolve - this ensures the resolved
        # instance supports dynamic override
        with (
            container.override(UserRepo, user_repo_mock),
            container.override(Annotated[str, "param"], "mock"),
        ):
            user_service = container.resolve(UserService)
            assert user_service.process() == {
                "user": "mocked_user",
                "param": "mock",
            }

    async def test_override_instance_async_resolved(self) -> None:
        container = Container()
        container.enable_test_mode()
        container.register(Annotated[str, "param"], lambda: "param", scope="singleton")

        @singleton
        class UserService:
            def __init__(self, param: Annotated[str, "param"]) -> None:
                self.param = param

            def process(self) -> dict[str, str]:
                return {
                    "param": self.param,
                }

        with container.override(Annotated[str, "param"], "mock"):
            user_service = await container.aresolve(UserService)
            assert user_service.process() == {
                "param": "mock",
            }

    def test_override_instance_in_strict_mode(self) -> None:
        container = Container()

        class Settings:
            def __init__(self, name: str) -> None:
                self.name = name

        @container.provider(scope="singleton")
        def provide_settings() -> Settings:
            return Settings(name="test")

        @container.provider(scope="singleton")
        def provide_service(settings: Settings) -> Service:
            return Service(ident=settings.name)

        service = container.resolve(Service)

        assert service.ident == "test"

    def test_override_instance_first(self) -> None:
        container = Container()
        container.enable_test_mode()

        @dataclass
        class Item:
            name: str

        class ItemRepository:
            def __init__(self, items: list[Item]) -> None:
                self.items = items

            def all(self) -> list[Item]:
                return self.items

        class ItemService:
            def __init__(self, repo: ItemRepository) -> None:
                self.repo = repo

            def get_items(self) -> list[Item]:
                return self.repo.all()

        @container.provider(scope="singleton")
        def provide_repo() -> ItemRepository:
            return ItemRepository(items=[])

        @container.provider(scope="singleton")
        def provide_service(repo: ItemRepository) -> ItemService:
            return ItemService(repo=repo)

        @container.inject
        def handler(service: ItemService = Inject()) -> list[Item]:
            return service.get_items()

        repo_mock = mock.MagicMock(spec=ItemRepository)
        repo_mock.all.return_value = [Item(name="mocked")]

        with container.override(ItemRepository, repo_mock):
            items = handler()
            assert items == [Item(name="mocked")]

        service = container.resolve(ItemService)
        assert service.get_items() == []

    def test_override_prevents_original_service_initialization(self) -> None:
        initialized = False

        class Service:
            def __init__(self) -> None:
                nonlocal initialized
                initialized = True

        container = Container()
        container.enable_test_mode()

        @container.provider(scope="singleton")
        def service() -> Service:
            return Service()

        service_mock = mock.MagicMock(spec=Service)

        with container.override(Service, service_mock):
            assert initialized is False

    def test_override_without_dict(self) -> None:
        class ServiceWithoutDict:
            __slots__ = ("value",)

            def __init__(self) -> None:
                self.value = 42

        container = Container()
        container.enable_test_mode()
        container.register(ServiceWithoutDict, scope="singleton")

        with container.override(ServiceWithoutDict, ServiceWithoutDict()):
            result = container.resolve(ServiceWithoutDict)
            assert result.value == 42

    def test_override_existing_override(self) -> None:
        @singleton
        class Service:
            def __init__(self) -> None:
                self.name = "original"

        container = Container()
        container.enable_test_mode()

        override_instance = Service()
        override_instance.name = "override"

        with container.override(Service, override_instance):
            result = container.resolve(Service)
            assert result.name == "override"
            assert result is override_instance

    def test_override_no_double_wrapping(self) -> None:
        container = Container()
        container.enable_test_mode()
        container.register(int, lambda: 1)

        instance = 2
        with container.override(int, instance):
            resolved = container.resolve(int)
            assert resolved == instance
            assert not isinstance(resolved, InstanceProxy)

    def test_override_deprecated_interface(self) -> None:
        container = Container()
        container.enable_test_mode()
        container.register(int, factory=lambda: 0)

        with pytest.warns(
            DeprecationWarning,
            match="The `interface` is deprecated. Use `dependency_type` instead.",
        ):
            with container.override(interface=int, instance=42):
                assert container.resolve(int) == 42

        assert container.resolve(int) == 0

    def test_override_canonical_resolves_via_alias(self) -> None:
        """Override canonical type, resolve via alias."""

        class IService:
            pass

        class ServiceImpl(IService):
            pass

        class MockService(IService):
            pass

        container = Container()
        container.enable_test_mode()
        container.register(ServiceImpl, scope="singleton")
        container.alias(IService, ServiceImpl)

        mock = MockService()
        with container.override(ServiceImpl, mock):
            assert container.resolve(IService) is mock
            assert container.resolve(ServiceImpl) is mock

    def test_override_alias_resolves_via_canonical(self) -> None:
        """Override alias type, resolve via canonical."""

        class IService:
            pass

        class ServiceImpl(IService):
            pass

        class MockService(IService):
            pass

        container = Container()
        container.enable_test_mode()
        container.register(ServiceImpl, scope="singleton")
        container.alias(IService, ServiceImpl)

        mock = MockService()
        with container.override(IService, mock):
            assert container.resolve(IService) is mock
            assert container.resolve(ServiceImpl) is mock

    async def test_override_alias_async(self) -> None:
        """Override with alias works in async resolution."""

        class IService:
            pass

        class ServiceImpl(IService):
            pass

        class MockService(IService):
            pass

        container = Container()
        container.enable_test_mode()
        container.register(ServiceImpl, scope="singleton")
        container.alias(IService, ServiceImpl)

        mock = MockService()
        with container.override(ServiceImpl, mock):
            assert await container.aresolve(IService) is mock
            assert await container.aresolve(ServiceImpl) is mock


# Test data for import_container tests
class _TestService:
    pass


_container_instance = Container()
_container_instance.register(_TestService, lambda: _TestService(), scope="singleton")


def _container_factory() -> Container:
    """Factory function that returns a container."""
    container = Container()
    container.register(_TestService, lambda: _TestService(), scope="singleton")
    return container


class TestImportContainer:
    """Tests for the import_container function."""

    def test_import_container_instance_colon_format(self) -> None:
        """Test importing a container instance from a string path (colon format)."""

        container = import_container("tests.test_container:_container_instance")
        assert isinstance(container, Container)
        assert container.has_provider_for(_TestService)

    def test_import_container_instance_dot_format(self) -> None:
        """Test importing a container instance (dot format, backward compatible)."""

        container = import_container("tests.test_container._container_instance")
        assert isinstance(container, Container)
        assert container.has_provider_for(_TestService)

    def test_import_container_factory_colon_format(self) -> None:
        """Test importing a container from a factory function (colon format)."""

        container = import_container("tests.test_container:_container_factory")
        assert isinstance(container, Container)
        assert container.has_provider_for(_TestService)

    def test_import_container_factory_dot_format(self) -> None:
        """Test importing container from factory (dot format, backward compatible)."""

        container = import_container("tests.test_container._container_factory")
        assert isinstance(container, Container)
        assert container.has_provider_for(_TestService)

    def test_import_container_invalid_path(self) -> None:
        """Test that invalid path raises ImportError."""

        with pytest.raises(ImportError, match="Invalid container path"):
            import_container("invalid_path")

    def test_import_container_missing_module(self) -> None:
        """Test that missing module raises ImportError."""

        with pytest.raises(ImportError, match="Failed to import module"):
            import_container("nonexistent.module:container")

    def test_import_container_missing_attribute(self) -> None:
        """Test that missing attribute raises ImportError."""

        with pytest.raises(ImportError, match="has no attribute"):
            import_container("tests.test_container:nonexistent")

    def test_import_container_wrong_type(self) -> None:
        """Test that wrong type raises ImportError."""

        with pytest.raises(ImportError, match="Expected Container instance"):
            import_container("tests.test_container:_TestService")


# Generic TypeVar resolution test fixtures
ModelT = TypeVar("ModelT", bound="Model")
U = TypeVar("U")
V = TypeVar("V")


class Model:
    pass


class User(Model):
    pass


class Guest(Model):
    pass


class Repository(Generic[ModelT]):
    pass


class UserRepository(Repository[User]):
    pass


class TestContainerGenericResolution:
    """Tests for generic TypeVar resolution in container."""

    def test_resolve_generic_handler(self) -> None:
        """Test resolving a class that inherits from a generic base."""

        class Handler(Generic[ModelT]):
            def __init__(self, repo: Repository[ModelT]) -> None:
                self.repo = repo

        class UserHandler(Handler[User]):
            pass

        container = Container()
        container.register(UserRepository, alias=Repository[User])
        container.register(UserHandler)

        handler = container.resolve(UserHandler)
        assert isinstance(handler, UserHandler)
        assert isinstance(handler.repo, UserRepository)

    def test_resolve_multi_level_generic(self) -> None:
        """Test resolving with multi-level generic inheritance."""

        class Service(Generic[U]):
            def __init__(self, repo: Repository[U]) -> None:  # type: ignore[type-var]
                self.repo = repo

        class MiddleUserService(Service[User]):
            pass

        class FinalService(MiddleUserService):
            pass

        container = Container()
        container.register(UserRepository, alias=Repository[User])
        container.register(FinalService)

        service = container.resolve(FinalService)
        assert isinstance(service, FinalService)
        assert isinstance(service.repo, UserRepository)

    def test_resolve_multiple_type_params(self) -> None:
        """Test resolving with multiple type parameters."""

        class Processor(Generic[U, V]):
            def __init__(self, input_repo: Repository[U]) -> None:  # type: ignore[type-var]
                self.input_repo = input_repo

        class UserGuestProcessor(Processor[User, Guest]):
            pass

        container = Container()
        container.register(UserRepository, alias=Repository[User])
        container.register(UserGuestProcessor)

        processor = container.resolve(UserGuestProcessor)
        assert isinstance(processor, UserGuestProcessor)
        assert isinstance(processor.input_repo, UserRepository)

    def test_resolve_without_generic_base(self) -> None:
        """Test that classes without generic bases work unchanged."""

        class SimpleService:
            def __init__(self, repo: UserRepository) -> None:
                self.repo = repo

        container = Container()
        container.register(UserRepository)
        container.register(SimpleService)

        service = container.resolve(SimpleService)
        assert isinstance(service, SimpleService)
        assert isinstance(service.repo, UserRepository)
