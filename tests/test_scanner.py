import importlib
import sys

import pytest
from pytest_mock import MockerFixture

from anydi import Container, singleton
from anydi._scanner import Scanner

from tests.fixtures import Service
from tests.scan_app import ScanAppModule
from tests.scan_app.c.services import IRepository, UserRepository


class TestContainerScanner:
    @pytest.fixture
    def container(self) -> Container:
        return Container()

    def test_scan_registers_all_dependencies(
        self, container: Container, mocker: MockerFixture
    ) -> None:
        inject_spy = mocker.spy(container, "inject")

        container.register_module(ScanAppModule)
        container.scan(["tests.scan_app"])

        # Expecting 4 total inject calls from all eligible @injectable functions
        assert inject_spy.call_count == 4

        from .scan_app.a.a3.handlers import a_a3_handler_1

        assert a_a3_handler_1() == "a.a1.str_provider"

    def test_scan_single_module_registers_limited_dependencies(
        self, container: Container, mocker: MockerFixture
    ) -> None:
        inject_spy = mocker.spy(container, "inject")

        container.register_module(ScanAppModule)
        container.scan("tests.scan_app.a.a3.handlers")

        # Expecting only 1 handler to be registered from this specific module
        assert inject_spy.call_count == 1

        from .scan_app.a.a3.handlers import a_a3_handler_1

        assert a_a3_handler_1() == "a.a1.str_provider"

    def test_scan_with_unknown_tag_registers_nothing(
        self, container: Container, mocker: MockerFixture
    ) -> None:
        inject_spy = mocker.spy(container, "inject")

        container.scan(["tests.scan_app"], tags=["non_existing_tag"])

        # No injectable functions should be picked up with unmatched tags
        inject_spy.assert_not_called()

    def test_scan_with_matching_tag_registers_only_matching_dependencies(
        self, container: Container, mocker: MockerFixture
    ) -> None:
        inject_spy = mocker.spy(container, "inject")

        container.register_module(ScanAppModule)
        container.scan(["tests.scan_app"], tags=["inject"])

        # Only handlers with @injectable(..., tags=["inject"]) should be included
        assert inject_spy.call_count == 1

        from .scan_app.a.a3.handlers import a_a3_handler_1

        assert a_a3_handler_1() == "a.a1.str_provider"

    def test_scan_registers_provided_classes(
        self, container: Container, mocker: MockerFixture
    ) -> None:
        register_spy = mocker.spy(container, "register")

        container.scan(["tests.scan_app.c"])

        # Should register 3 @provided classes
        assert register_spy.call_count == 3

        from .scan_app.c.services import IRepository, SingletonService, TransientService

        # Verify classes are registered
        assert container.is_registered(SingletonService)
        assert container.is_registered(TransientService)
        assert container.is_registered(IRepository)

        # Verify they can be resolved
        singleton_service = container.resolve(SingletonService)
        assert singleton_service.name == "singleton_service"

        transient_service = container.resolve(TransientService)
        assert transient_service.name == "transient_service"
        assert transient_service.singleton_service is singleton_service

    def test_scan_skips_already_registered_provided_classes(
        self, container: Container, mocker: MockerFixture
    ) -> None:
        from .scan_app.c.services import SingletonService

        # Manually register the class first
        container.register(SingletonService)

        register_spy = mocker.spy(container, "register")

        container.scan(["tests.scan_app.c"])

        # Should register TransientService and UserRepository
        assert register_spy.call_count == 2

        # Verify both classes are registered
        assert container.is_registered(SingletonService)

    def test_scan_registers_provided_class_with_alias(
        self, container: Container
    ) -> None:
        container.scan(["tests.scan_app.c"])

        # Verify class is registered
        assert container.is_registered(UserRepository)

        # Resolve by class
        repo = container.resolve(UserRepository)
        assert isinstance(repo, UserRepository)
        assert repo.get(1) == {"id": 1, "name": "Alice"}

        # Resolve by alias (interface)
        repo2 = container.resolve(IRepository)
        assert repo is repo2

    def test_scan_creates_alias_for_interface(self, container: Container) -> None:
        container.scan(["tests.scan_app.c"])

        # Verify alias is created (IRepository → UserRepository)
        assert IRepository in container.aliases
        assert container.aliases[IRepository] == UserRepository

        # Verify both types can be resolved
        assert container.is_registered(UserRepository)
        assert container.is_registered(IRepository)

        # Verify both resolve to the same instance
        repo_by_class = container.resolve(UserRepository)
        repo_by_interface = container.resolve(IRepository)
        assert repo_by_class is repo_by_interface

    def test_scan_creates_multiple_aliases(self, container: Container) -> None:
        class IReader:
            pass

        class IWriter:
            pass

        @singleton(alias=[IReader, IWriter])
        class ReadWriteService(IReader, IWriter):
            pass

        # Manually register for this test
        container.register(ReadWriteService, scope="singleton")
        container.alias(IReader, ReadWriteService)
        container.alias(IWriter, ReadWriteService)

        # All three should resolve to the same instance
        service = container.resolve(ReadWriteService)
        reader = container.resolve(IReader)
        writer = container.resolve(IWriter)

        assert service is reader
        assert service is writer
        assert reader is writer

    def test_scan_ignore_package_with_string(self) -> None:
        """Test ignoring a package using string path."""
        from tests.scan_app.a.a1 import handlers as a1_handlers
        from tests.scan_app.b import handlers as b_handlers

        b_handlers = importlib.reload(b_handlers)
        a1_handlers = importlib.reload(a1_handlers)

        container = Container()
        container.register(str, lambda: "hello")
        container.register(Service, Service)

        # Check initial state
        assert not hasattr(b_handlers.b_handler, "__wrapped__")
        assert not hasattr(a1_handlers.a1_handler, "__wrapped__")

        # Scan with ignore
        container.scan("tests.scan_app", ignore=["tests.scan_app.b"])

        # Verify module identity
        assert a1_handlers is sys.modules["tests.scan_app.a.a1.handlers"]

        # b_handlers should be ignored
        assert not hasattr(b_handlers.b_handler, "__wrapped__"), (
            "b_handlers.b_handler should not be wrapped (ignored)"
        )

        # a1_handlers should be scanned
        assert hasattr(a1_handlers.a1_handler, "__wrapped__"), (
            "a1_handlers.a1_handler should be wrapped (scanned)"
        )

    def test_scan_ignore_package_with_module(self) -> None:
        """Test ignoring a package using module object."""
        import tests.scan_app.b as b_package
        from tests.scan_app.a.a1 import handlers as a1_handlers
        from tests.scan_app.b import handlers as b_handlers

        b_handlers = importlib.reload(b_handlers)
        a1_handlers = importlib.reload(a1_handlers)

        container = Container()
        container.register(str, lambda: "hello")
        container.register(Service, Service)

        # Scan with ignore using module object
        container.scan("tests.scan_app", ignore=[b_package])

        # b_handlers should be ignored
        assert not hasattr(b_handlers.b_handler, "__wrapped__")

        # a1_handlers should be scanned
        assert hasattr(a1_handlers.a1_handler, "__wrapped__")

    def test_scan_ignore_single_string(self) -> None:
        """Test ignoring a single string (not a list)."""
        from tests.scan_app.a.a1 import handlers as a1_handlers
        from tests.scan_app.b import handlers as b_handlers

        b_handlers = importlib.reload(b_handlers)
        a1_handlers = importlib.reload(a1_handlers)

        container = Container()
        container.register(str, lambda: "hello")
        container.register(Service, Service)

        # Scan with ignore as single string
        container.scan("tests.scan_app", ignore="tests.scan_app.b")

        # b_handlers should be ignored
        assert not hasattr(b_handlers.b_handler, "__wrapped__")

        # a1_handlers should be scanned
        assert hasattr(a1_handlers.a1_handler, "__wrapped__")

    def test_scan_ignore_multiple_packages(self) -> None:
        """Test ignoring multiple packages."""
        from tests.scan_app.a.a1 import handlers as a1_handlers
        from tests.scan_app.a.a3 import handlers as a3_handlers
        from tests.scan_app.b import handlers as b_handlers

        b_handlers = importlib.reload(b_handlers)
        a1_handlers = importlib.reload(a1_handlers)
        a3_handlers = importlib.reload(a3_handlers)

        container = Container()
        container.register(str, lambda: "hello")
        container.register(Service, Service)

        # Scan with multiple ignores
        container.scan(
            "tests.scan_app",
            ignore=["tests.scan_app.b", "tests.scan_app.a.a3"],
        )

        # b_handlers and a3_handlers should be ignored
        assert not hasattr(b_handlers.b_handler, "__wrapped__")
        assert not hasattr(a3_handlers.a_a3_handler_1, "__wrapped__")

        # a1_handlers should be scanned
        assert hasattr(a1_handlers.a1_handler, "__wrapped__")

    def test_scan_detects_circular_import(self, container: Container) -> None:
        """Test that circular imports during scanning are detected."""
        scanner = Scanner(container)
        # Simulate a module already being in the import chain
        scanner._importing_modules.add("tests.scan_app.circular_module")

        with pytest.raises(RuntimeError) as exc_info:
            # This should raise because the module is already being imported
            list(scanner._import_module_with_tracking("tests.scan_app.circular_module"))

        error_message = str(exc_info.value)
        assert "Circular import detected" in error_message
        assert "tests.scan_app.circular_module" in error_message
        assert "Solutions:" in error_message

    def test_scan_detects_recursive_scan_call(self, container: Container) -> None:
        """Test that recursive scan() calls are detected (e.g., via lazy proxy)."""
        scanner = Scanner(container)
        # Simulate scan already in progress
        scanner._scanning = True

        with pytest.raises(RuntimeError) as exc_info:
            scanner.scan("tests.scan_app")

        error_message = str(exc_info.value)
        assert "scan() called recursively" in error_message
        assert "Solutions:" in error_message
