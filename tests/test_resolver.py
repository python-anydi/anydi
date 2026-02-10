import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

import anydi._types
from anydi import Container
from anydi._provider import Provider, ProviderParameter
from anydi._resolver import InstanceProxy
from anydi._types import NOT_SET as ANYDI_NOT_SET


class TestResolver:
    def test_compile_with_removed_provider(self) -> None:
        class Dependency:
            pass

        class Service:
            def __init__(self, dep: Dependency) -> None:
                self.dep = dep

        container = Container()
        resolver = container._resolver

        container.register(Dependency, scope="singleton")
        service_provider = container.register(Service, scope="singleton")

        resolver.compile(service_provider, is_async=False)

        del container.providers[Dependency]

        resolver.compile(service_provider, is_async=False)

    def test_lazy_compile_with_removed_provider(self) -> None:
        class Dependency:
            pass

        class Service:
            def __init__(self, dep: Dependency) -> None:
                self.dep = dep

        container = Container()
        resolver = container._resolver

        container.register(Dependency, scope="singleton")
        container.register(Service, scope="singleton")

        service_provider = container.providers[Service]

        del container.providers[Dependency]

        resolver.clear_caches()
        resolver.compile(service_provider, is_async=False)

    def test_custom_scope_with_override(self) -> None:
        class Service:
            def __init__(self) -> None:
                self.name = "original"

        container = Container()
        container.register(Service, scope="request")
        resolver = container._resolver

        override_instance = Service()
        override_instance.name = "override"
        resolver.add_override(Service, override_instance)

        service_provider = container.providers[Service]
        resolver.compile(service_provider, is_async=False)

        resolver.remove_override(Service)

    def test_resolver_override_check_include_not_set(self) -> None:
        """Test override check with include_not_set=True logic."""
        container = Container()
        container.enable_test_mode()

        class Service:
            def __init__(self, val: int) -> None:
                self.val = val

        container.register(int, lambda: 1, scope="transient")
        container.register(Service, scope="transient")

        with container.override(int, 2):
            service = container.resolve(Service)
            assert service.val == 2

    async def test_resolver_async_override(self) -> None:
        """Test async resolution with override."""
        container = Container()
        container.enable_test_mode()
        container.register(int, lambda: 1, scope="singleton")

        with container.override(int, 2):
            val = await container.aresolve(int)
            assert val == 2

    def test_resolver_from_context_with_override(self) -> None:
        """Test from_context provider with override."""
        container = Container()
        container.enable_test_mode()
        container.register(int, scope="request", from_context=True)

        with container.request_context():
            with container.override(int, 100):
                assert container.resolve(int) == 100

    async def test_resolver_async_from_context_with_override(self) -> None:
        """Test async from_context provider with override."""
        container = Container()
        container.enable_test_mode()
        container.register(int, scope="request", from_context=True)

        async with container.arequest_context():
            with container.override(int, 100):
                assert await container.aresolve(int) == 100

    def test_resolver_post_resolve_override_nested(self) -> None:
        """Test nested dependency override patching."""
        container = Container()
        container.enable_test_mode()

        class Config:
            def __init__(self, val: int) -> None:
                self.val = val

        class Service:
            def __init__(self, config: Config) -> None:
                self.config = config

        container.register(int, lambda: 1, scope="singleton")
        container.register(Config, scope="singleton")
        container.register(Service, scope="singleton")

        container.register(str, lambda: "dummy", scope="singleton")

        with container.override(str, "active"):
            # Service created here should support nested overrides
            service = container.resolve(Service)

            mock_config = Config(2)
            with container.override(Config, mock_config):
                assert service.config.val == 2

    def test_resolver_override_not_set(self) -> None:
        """Test _get_override_for when not set."""
        container = Container()
        container.enable_test_mode()
        container.register(int, lambda: 1, scope="singleton")
        container.register(str, lambda: "s", scope="singleton")

        with container.override(str, "test"):
            assert container.resolve(int) == 1

    def test_instance_proxy_dependency_type(self) -> None:
        """Test InstanceProxy.dependency_type property."""
        proxy = InstanceProxy(1, dependency_type=int)
        # Use object.__getattribute__ to bypass proxy delegation
        assert object.__getattribute__(proxy, "_self_dependency_type") is int

    def test_instance_proxy_callable(self) -> None:
        """Test that InstanceProxy properly delegates __call__ to wrapped object."""

        class Callable:
            def __call__(self) -> str:
                return "HELLO"

        proxy = InstanceProxy(Callable(), dependency_type=Callable)
        assert proxy() == "HELLO"

    def test_callable_dependency_in_test_mode(self) -> None:
        """Test that callable dependencies work in test mode (override mode)."""

        class Callable:
            def __call__(self) -> str:
                return "HELLO"

        container = Container()

        @container.provider(scope="singleton")
        def provide_callable() -> Callable:
            return Callable()

        @container.provider(scope="singleton")
        def provide_str(c: Callable) -> str:
            return c()

        container.enable_test_mode()

        assert container.resolve(str) == "HELLO"

    def test_resolver_compile_from_context_create_error(self) -> None:
        """Test that calling create() on a from_context provider raises TypeError."""
        container = Container()
        container.register(int, scope="request", from_context=True)

        with pytest.raises(
            TypeError, match="Cannot create instance for from_context provider"
        ):
            container.create(int)

    def test_resolver_post_resolve_override_no_dict(self) -> None:
        """Test _post_resolve_override with an instance that has no __dict__."""
        container = Container()
        resolver = container._resolver
        assert resolver._post_resolve_override(int, 1) == 1

    def test_resolver_post_resolve_override_with_slots(self) -> None:
        """Test _post_resolve_override with an instance that has __slots__."""

        class Slotted:
            __slots__ = ("val",)

            def __init__(self):
                self.val = 1

        container = Container()
        resolver = container._resolver
        instance = Slotted()
        assert resolver._post_resolve_override(Slotted, instance) is instance

    def test_resolver_post_resolve_override_already_patched(self) -> None:
        """Test _post_resolve_override with an already patched instance."""

        class Service:
            pass

        container = Container()
        resolver = container._resolver
        instance = Service()
        instance.__resolver_getter__ = lambda name: None  # type: ignore
        assert resolver._post_resolve_override(Service, instance) is instance

    def test_resolver_post_resolve_override_direct_match(self) -> None:
        """Test _post_resolve_override where dependency_type is in overrides."""
        container = Container()
        resolver = container._resolver
        resolver.add_override(int, 42)
        assert resolver._post_resolve_override(int, 1) == 42

    def test_resolver_wrap_for_override_already_proxy(self) -> None:
        """Test _wrap_for_override with an already InstanceProxy instance."""
        container = Container()
        resolver = container._resolver
        proxy = InstanceProxy(1, dependency_type=int)
        assert resolver._wrap_for_override(int, proxy) is proxy

    def test_resolver_unresolved_parameter_message(self) -> None:
        """Test the unresolved parameter message logic in _compile_resolver."""
        container = Container()

        def my_func(unregistered: int) -> int:
            return unregistered

        provider = Provider(
            dependency_type=Any,
            factory=my_func,
            scope="transient",
            from_context=False,
            parameters=(
                ProviderParameter(
                    dependency_type=int,
                    name="unregistered",
                    default=None,
                    has_default=False,
                    provider=None,
                ),
            ),
            is_class=False,
            is_coroutine=False,
            is_generator=False,
            is_async_generator=False,
            is_async=False,
            is_resource=False,
        )

        compiled = container._resolver.compile(provider, is_async=False)

        with pytest.raises(
            LookupError, match="You are attempting to get the parameter `unregistered`"
        ):
            compiled.resolve(container)

    def test_resolver_compile_fallback_original_provider(self) -> None:
        """Test fallback to original provider in compile()."""
        container = Container()
        resolver = container._resolver

        def my_main_func(i: int) -> str:
            return str(i)

        sub_provider = Provider(
            dependency_type=int,
            factory=lambda: 42,
            scope="singleton",
            from_context=False,
            parameters=(),
            is_class=False,
            is_coroutine=False,
            is_generator=False,
            is_async_generator=False,
            is_async=False,
            is_resource=False,
        )

        main_provider = Provider(
            dependency_type=str,
            factory=my_main_func,
            scope="singleton",
            from_context=False,
            parameters=(
                ProviderParameter(
                    dependency_type=int,
                    name="i",
                    default=None,
                    has_default=False,
                    provider=sub_provider,
                ),
            ),
            is_class=False,
            is_coroutine=False,
            is_generator=False,
            is_async_generator=False,
            is_async=False,
            is_resource=False,
        )

        # Ensure int is NOT in container.providers
        assert int not in container.providers

        resolver.compile(main_provider, is_async=False)
        assert str in resolver._cache

    def test_resolver_get_cached_async_override(self) -> None:
        """Test get_cached with is_async=True and override_mode=True."""
        container = Container()
        container.enable_test_mode()
        resolver = container._resolver
        container.register(int, lambda: 1)

        with container.override(int, 2):
            asyncio.run(container.aresolve(int))
            assert resolver.get_cached(int, is_async=True) is not None

    def test_resolver_is_coroutine_sync_mode_raises(self) -> None:
        """Test that resolving a coroutine provider in sync mode raises TypeError."""
        container = Container()

        @container.provider(scope="singleton")
        async def my_coro() -> int:
            return 42

        with pytest.raises(TypeError, match="cannot be created in synchronous mode"):
            container.resolve(int)

    def test_resolver_is_async_generator_no_context(self) -> None:
        """Test that async generator provider without context raises ValueError."""
        container = Container()

        async def my_agen() -> AsyncIterator[int]:
            yield 42

        provider = Provider(
            dependency_type=str,
            factory=my_agen,
            scope="transient",
            from_context=False,
            parameters=(),
            is_class=False,
            is_coroutine=False,
            is_generator=False,
            is_async_generator=True,
            is_async=True,
            is_resource=True,
        )

        compiled = container._resolver.compile(provider, is_async=True)

        with pytest.raises(ValueError, match="async stack is required"):
            asyncio.run(compiled.create(container))

    def test_resolver_is_generator_no_context(self) -> None:
        """Test that generator provider without context raises ValueError."""
        container = Container()

        def my_gen() -> Iterator[int]:
            yield 42

        provider = Provider(
            dependency_type=int,
            factory=my_gen,
            scope="transient",
            from_context=False,
            parameters=(),
            is_class=False,
            is_coroutine=False,
            is_generator=True,
            is_async_generator=False,
            is_async=False,
            is_resource=True,
        )

        compiled = container._resolver.compile(provider, is_async=False)

        with pytest.raises(ValueError, match="context is required"):
            compiled.create(container)

    def test_resolver_add_remove_override(self) -> None:
        """Test add_override and remove_override directly on resolver."""
        container = Container()

        resolver = container._resolver
        resolver.add_override(int, 10)

        assert resolver.override_mode is True
        assert resolver._get_override_for(int) == 10

        resolver.remove_override(int)

        assert resolver.override_mode is False
        assert resolver._get_override_for(int) is anydi._types.NOT_SET

    def test_resolver_override_not_found(self) -> None:
        """Test _get_override_for when type is not in overrides."""
        container = Container()
        resolver = container._resolver
        resolver.add_override(int, 10)
        assert resolver._get_override_for(str) is ANYDI_NOT_SET

    def test_resolver_clear_caches(self) -> None:
        """Test clear_caches on resolver."""
        container = Container()
        resolver = container._resolver
        container.register(int, lambda: 1)
        container.resolve(int)
        assert int in resolver._cache
        resolver.clear_caches()
        assert int not in resolver._cache

    def test_resolver_post_resolve_override_complex(self) -> None:
        """Test complex _post_resolve_override scenario with InstanceProxy."""
        container = Container()
        container.enable_test_mode()

        class Dependency:
            def __init__(self, val: int):
                self.val = val

        class Service:
            def __init__(self, dep: Dependency):
                self.dep = dep

        container.register(int, lambda: 1)
        container.register(Dependency, scope="singleton")
        container.register(Service, scope="singleton")
        container.register(str, lambda: "s")

        with container.override(str, "trigger"):
            service = container.resolve(Service)

            # Test __resolver_getter__
            val = service.__resolver_getter__("dep")  # type: ignore
            assert isinstance(val, Dependency)

            with pytest.raises(LookupError):
                service.__resolver_getter__("nonexistent")  # type: ignore

            # Test dynamic patching behavior
            assert service.dep.val == 1

            with container.override(Dependency, Dependency(2)):
                assert service.dep.val == 2

            # Test already patched class path
            container._resolver._post_resolve_override(Service, service)

    def test_resolver_alias_caching(self) -> None:
        """Test that resolving via alias uses the same cache entry."""

        class IService:
            pass

        class ServiceImpl(IService):
            pass

        container = Container()
        container.register(ServiceImpl, scope="singleton")
        container.alias(IService, ServiceImpl)

        # Resolve via concrete type
        instance1 = container.resolve(ServiceImpl)

        # Resolve via alias - should get same instance
        instance2 = container.resolve(IService)

        assert instance1 is instance2

    def test_resolver_compile_with_alias_dependency(self) -> None:
        """Test that compile() correctly resolves alias when looking up dependency."""

        class IRepository:
            pass

        class RepositoryImpl(IRepository):
            pass

        class Service:
            def __init__(self, repo: IRepository) -> None:
                self.repo = repo

        container = Container()
        container.register(RepositoryImpl, scope="singleton")
        container.alias(IRepository, RepositoryImpl)
        container.register(Service, scope="singleton")

        # Service depends on IRepository (alias) - resolver should find RepositoryImpl
        service = container.resolve(Service)
        assert isinstance(service.repo, RepositoryImpl)

    def test_resolver_compile_with_alias_dependency_override(self) -> None:
        """Test that override works when dependency uses alias type."""

        class IRepository:
            def get_data(self) -> str:
                return "base"

        class RepositoryImpl(IRepository):
            def get_data(self) -> str:
                return "impl"

        class MockRepository(IRepository):
            def get_data(self) -> str:
                return "mock"

        class Service:
            def __init__(self, repo: IRepository) -> None:
                self.repo = repo

        container = Container()
        container.enable_test_mode()
        container.register(RepositoryImpl, scope="singleton")
        container.alias(IRepository, RepositoryImpl)
        container.register(Service, scope="singleton")

        # Override canonical type - should affect Service's dependency
        with container.override(RepositoryImpl, MockRepository()):
            service = container.resolve(Service)
            assert service.repo.get_data() == "mock"

    def test_resolver_override_via_alias(self) -> None:
        """Test that override on canonical type works when resolving via alias."""

        class IService:
            def get_value(self) -> int:
                return 0

        class ServiceImpl(IService):
            def get_value(self) -> int:
                return 1

        class MockService(IService):
            def get_value(self) -> int:
                return 999

        container = Container()
        container.enable_test_mode()
        container.register(ServiceImpl, scope="singleton")
        container.alias(IService, ServiceImpl)

        # Override the canonical type
        with container.override(ServiceImpl, MockService()):
            # Resolve via alias should get the override
            result = container.resolve(IService)
            assert result.get_value() == 999

    def test_resolver_override_via_alias_direct(self) -> None:
        """Test that override on alias type also overrides canonical type."""

        class IService:
            def get_value(self) -> int:
                return 0

        class ServiceImpl(IService):
            def get_value(self) -> int:
                return 1

        class MockService(IService):
            def get_value(self) -> int:
                return 999

        container = Container()
        container.enable_test_mode()
        container.register(ServiceImpl, scope="singleton")
        container.alias(IService, ServiceImpl)

        # Override the alias type - should affect both alias and canonical
        with container.override(IService, MockService()):
            # Resolve via alias should get the override
            result = container.resolve(IService)
            assert result.get_value() == 999

            # Resolve via canonical should also get the override
            result2 = container.resolve(ServiceImpl)
            assert result2.get_value() == 999
