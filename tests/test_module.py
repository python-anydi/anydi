from typing import Annotated

import pytest

from anydi import Container, Module, provider

from tests.fixtures import TestModule


class TestContainerModuleRegistrator:
    @pytest.fixture
    def container(self) -> Container:
        return Container()

    def test_register_modules(self) -> None:
        container = Container(modules=[TestModule])

        assert container.is_registered(Annotated[str, "msg1"])
        assert container.is_registered(Annotated[str, "msg2"])

    def test_register_module_class(self, container: Container) -> None:
        container.register_module(TestModule)

        assert container.is_registered(Annotated[str, "msg1"])
        assert container.is_registered(Annotated[str, "msg2"])

    def test_register_module_instance(self, container: Container) -> None:
        container.register_module(TestModule())

        assert container.is_registered(Annotated[str, "msg1"])
        assert container.is_registered(Annotated[str, "msg2"])

    def test_register_module_path(self, container: Container) -> None:
        container.register_module("tests.test_module.TestModule")

        assert container.is_registered(Annotated[str, "msg1"])
        assert container.is_registered(Annotated[str, "msg2"])

    def test_register_module_function(self, container: Container) -> None:
        def configure(_container: Container) -> None:
            _container.register(str, lambda: "Message 1", scope="singleton")

        container.register_module(configure)

        assert container.is_registered(str)

    def test_register_module_package(self, container: Container) -> None:
        with pytest.raises(TypeError, match="The module must be a callable"):
            container.register_module("os")

    def test_import_module_invalid_name(self, container: Container) -> None:
        with pytest.raises(ImportError, match="Cannot import 'nonexistent_module_xyz'"):
            container.register_module("nonexistent_module_xyz")

    def test_register_module_ordered_providers(self, container: Container) -> None:
        class OrderedModule(Module):
            @provider(scope="singleton")
            def dep3(self) -> Annotated[str, "dep3"]:
                return "dep3"

            @provider(scope="singleton")
            def dep1(self) -> Annotated[str, "dep1"]:
                return "dep1"

            @provider(scope="singleton")
            def dep2(self) -> Annotated[str, "dep2"]:
                return "dep2"

        container.register_module(OrderedModule)

        expected_providers = [
            Annotated[str, "dep3"],
            Annotated[str, "dep1"],
            Annotated[str, "dep2"],
        ]

        assert set(expected_providers).issubset(container.providers.keys())

        filtered = [k for k in container.providers.keys() if k in expected_providers]

        assert filtered == expected_providers

    def test_register_module_invalid_path(self, container: Container) -> None:
        with pytest.raises(
            TypeError,
            match=(
                r"The module must be a callable, a module type, or a module instance."
            ),
        ):
            container.register_module("anydi.Container")

    def test_register_module_with_override_scoped_provider(
        self, container: Container
    ) -> None:
        class Component1:
            def __init__(self, name: str) -> None:
                self.name = name

        class Component2:
            def __init__(self, component: Component1) -> None:
                self.component = component

        class AppModule(Module):
            @provider(scope="singleton")
            def component1(self) -> Component1:
                return Component1(name="origin")

            @provider(scope="singleton")
            def component2(self, component1: Component1) -> Component2:
                return Component2(component=component1)

        class TestModule(Module):
            @provider(scope="singleton", override=True)
            def component1(self) -> Component1:
                return Component1(name="override")

        container.register_module(AppModule)
        container.register_module(TestModule)

        # When Component2 is resolved, it should use the overridden Component1
        result = container.resolve(Component2)
        assert result.component.name == "override"

    def test_register_module_provider_with_alias(self, container: Container) -> None:
        class IDatabase:
            pass

        class Database(IDatabase):
            pass

        class AppModule(Module):
            @provider(scope="singleton", alias=IDatabase)
            def database(self) -> Database:
                return Database()

        container.register_module(AppModule)

        assert container.is_registered(IDatabase)
        assert container.is_registered(Database)

        db1 = container.resolve(IDatabase)
        db2 = container.resolve(Database)
        assert db1 is db2
        assert isinstance(db1, Database)

    def test_register_module_provider_with_multiple_aliases(
        self, container: Container
    ) -> None:
        class ICache:
            pass

        class IStore:
            pass

        class RedisCache(ICache, IStore):
            pass

        class CacheModule(Module):
            @provider(scope="singleton", alias=[ICache, IStore])
            def cache(self) -> RedisCache:
                return RedisCache()

        container.register_module(CacheModule)

        cache1 = container.resolve(ICache)
        cache2 = container.resolve(IStore)
        cache3 = container.resolve(RedisCache)
        assert cache1 is cache2 is cache3
