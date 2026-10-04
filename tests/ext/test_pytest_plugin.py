import sys
from typing import Annotated, Any
from unittest import mock

import pytest

from anydi import (
    Container,
    Inject,
    Provide,
    get_global_container,
    get_global_container_or_none,
    global_ref,
)
from anydi.ext import pytest_plugin

if "-p" not in sys.argv or "anydi" not in sys.argv:
    pytest.skip(
        "Plugin tests are skipped by default; run with -p anydi.",  # ty: ignore[too-many-positional-arguments]
        allow_module_level=True,
    )


class Repository:
    """Repository for testing override scenarios."""

    def get(self, item_id: int) -> dict[str, Any] | None:
        return None


class Service:
    """Service with repository dependency for testing."""

    name = "service"

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        return self.repo.get(item_id)


@pytest.fixture(scope="session")
def container() -> Container:
    container = Container()
    container.register(Repository)
    container.register(Service)
    return container


def test_anydi_autoinject_default(request: pytest.FixtureRequest) -> None:
    assert request.config.getini("anydi_autoinject") is True


def test_no_container_setup(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Store original getini
    original_getini = request.config.getini

    # No config set
    def mock_getini(key: str):  # type: ignore[no-untyped-def]
        if key == "anydi_container":
            return None
        return original_getini(key)

    monkeypatch.setattr(request.config, "getini", mock_getini)

    with pytest.raises(pytest.FixtureLookupError) as exc_info:
        pytest_plugin._find_container(request)

    assert exc_info.value.msg is not None
    assert (
        "`container` fixture is not found and 'anydi_container' config is not set"
        in exc_info.value.msg
    )


def test_get_global_container_from_config(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that container can be loaded from config (colon format)."""

    # Store original getini
    original_getini = request.config.getini

    # Set the config option
    def mock_getini(key: str):  # type: ignore[no-untyped-def]
        if key == "anydi_container":
            return "tests.test_container:_container_instance"
        return original_getini(key)

    monkeypatch.setattr(request.config, "getini", mock_getini)

    container = pytest_plugin._find_container(request)
    assert isinstance(container, Container)


def test_get_global_container_from_config_dot_format(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test container can be loaded from config (dot format, backward compatible)."""

    # Store original getini
    original_getini = request.config.getini

    # Set the config option
    def mock_getini(key: str) -> Any:
        if key == "anydi_container":
            return "tests.test_container._container_instance"
        return original_getini(key)

    monkeypatch.setattr(request.config, "getini", mock_getini)

    _container = pytest_plugin._find_container(request)
    assert isinstance(_container, Container)


def test_get_global_container_fixture_priority(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that fixture takes priority over config."""
    # Store original getini
    original_getini = request.config.getini

    # Set the config option to a different container
    def mock_getini(key: str) -> Any:
        if key == "anydi_container":
            return "tests.test_container:_container_factory"
        return original_getini(key)

    monkeypatch.setattr(request.config, "getini", mock_getini)

    # Should use the fixture, not the config
    _container = pytest_plugin._find_container(request)
    assert isinstance(_container, Container)


def test_get_global_container_no_fixture_no_config(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test error when neither fixture nor config is available."""
    # Store original getini
    original_getini = request.config.getini

    # No config set
    def mock_getini(key: str):  # type: ignore[no-untyped-def]
        if key == "anydi_container":
            return None
        return original_getini(key)

    monkeypatch.setattr(request.config, "getini", mock_getini)

    with pytest.raises(
        pytest.FixtureLookupError, match=r"container.*fixture is not found"
    ):
        pytest_plugin._find_container(request)


def test_container_test_mode_enabled(container: Container) -> None:
    """Test that container is in test mode when enable_test_mode is called."""
    assert container._test_mode is True


def test_override_works_for_injected_service(
    container: Container, service: Provide[Service]
) -> None:
    """Test that override works for already-resolved injected services."""

    # Verify service works with original repository
    assert service.get_item(100) is None

    # Create mock repository
    repo_mock = mock.MagicMock(spec=Repository)
    repo_mock.get.return_value = {"id": 100, "name": "mocked"}

    # Override should work for the already-injected service
    with container.override(Repository, instance=repo_mock):
        item = service.get_item(100)

        assert item is not None
        assert item["id"] == 100
        assert item["name"] == "mocked"

    # After override context, original behavior is restored
    assert service.get_item(100) is None


def test_explicit_provide_in_test(service: Provide[Service]) -> None:
    """Test explicit injection via Provide[T] in test functions."""
    assert isinstance(service, Service)
    assert service.name == "service"


async def test_explicit_provide_in_async_test(service: Provide[Service]) -> None:
    """Test explicit injection via Provide[T] in async test functions."""
    assert isinstance(service, Service)
    assert service.name == "service"


def test_explicit_annotated_inject_in_test(
    service: Annotated[Service, Inject()],
) -> None:
    """Test explicit injection via Annotated[T, Inject()] in test functions."""
    assert isinstance(service, Service)
    assert service.name == "service"


async def test_explicit_annotated_inject_in_async_test(
    service: Annotated[Service, Inject()],
) -> None:
    """Test explicit injection via Annotated[T, Inject()] in async test functions."""
    assert isinstance(service, Service)
    assert service.name == "service"


@pytest.fixture
def settings_fixture() -> dict[str, str]:
    """Regular pytest fixture."""
    return {"env": "test", "debug": "true"}


def test_mixed_params_in_test(
    service: Provide[Service],
    settings_fixture: dict[str, str],
) -> None:
    """Test mixing DI injection with regular pytest fixtures in test function."""
    assert isinstance(service, Service)
    assert settings_fixture == {"env": "test", "debug": "true"}


def test_explicit_injection_priority(
    repo: Provide[Repository],  # Explicit - should be injected
    container: Container,  # Regular fixture - should use fixture
) -> None:
    """Test that explicit markers take priority and coexist with fixtures."""
    assert isinstance(repo, Repository)
    assert isinstance(container, Container)


# A module-level reference, created before any container exists
global_service = global_ref(Service)


def test_global_ref_uses_container_fixture(container: Container) -> None:
    """Test that a global reference resolves through the container fixture."""
    assert get_global_container() is container
    assert global_service.name == "service"


def test_global_ref_follows_override(container: Container) -> None:
    """Test that overriding the container fixture applies to a global reference."""
    service_mock = mock.Mock(spec=Service)
    service_mock.name = "overridden"

    with container.override(Service, service_mock):
        assert global_service.name == "overridden"

    assert global_service.name == "service"


_APP = """
from anydi import Container


class Repository:
    pass


container = Container()
container.register(Repository)
"""

_OVERRIDING_CONFTEST = """
from unittest import mock

import pytest

from app import Repository, container


@pytest.fixture(scope="session", autouse=True)
def session_repo():
    with container.override(Repository, mock.sentinel.session_repo):
        yield


@pytest.fixture(autouse=True)
def function_repo():
    with container.override(Repository, mock.sentinel.function_repo):
        yield
"""


def _write_ini(pytester: pytest.Pytester, **options: str) -> None:
    lines = "\n".join(f"{key} = {value}" for key, value in options.items())
    pytester.makeini(f"[pytest]\n{lines}\n")


def test_disabled_plugin_adds_nothing(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(app=_APP)
    _write_ini(pytester, anydi="false", anydi_container="app:container")
    pytester.makepyfile(
        test_disabled="""
        from anydi import get_global_container_or_none
        from app import Repository, container


        def test_untouched():
            assert container._test_mode is False
            assert get_global_container_or_none() is None


        def test_no_injection(repo: Repository):
            pass


        def test_no_fixture(container):
            pass
        """
    )

    result = pytester.runpytest_subprocess()

    result.assert_outcomes(passed=1, errors=2)
    result.stdout.fnmatch_lines(["*fixture 'repo' not found*"])
    result.stdout.fnmatch_lines(["*fixture 'container' not found*"])


@pytest.mark.parametrize(
    "order",
    [
        ["test_a.py", "test_b.py"],
        ["test_b.py", "test_a.py"],
    ],
)
def test_overrides_in_test_mode_whatever_runs_first(
    pytester: pytest.Pytester, order: list[str]
) -> None:
    pytester.makepyfile(app=_APP, conftest=_OVERRIDING_CONFTEST)
    _write_ini(pytester, anydi_container="app:container")
    pytester.makepyfile(
        test_a="""
        from unittest import mock

        from app import Repository


        def test_without_fixture(repo: Repository):
            assert repo is mock.sentinel.function_repo
        """,
        test_b="""
        from app import container as app_container


        def test_with_fixture(container):
            assert container is app_container
            assert container._test_mode is True
        """,
    )

    result = pytester.runpytest_subprocess("-W", "error::UserWarning", *order)

    result.assert_outcomes(passed=2)


def test_global_container_created_at_collection(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        app="""
        from anydi import create_global_container


        class Repository:
            pass


        container = create_global_container()
        container.register(Repository)
        """
    )
    _write_ini(pytester)
    pytester.makepyfile(
        test_global="""
        from unittest import mock

        from app import Repository, container


        def test_override():
            assert container._test_mode is True
            with container.override(Repository, mock.sentinel.repo):
                assert container.resolve(Repository) is mock.sentinel.repo
        """
    )

    result = pytester.runpytest_subprocess("-W", "error::UserWarning")

    result.assert_outcomes(passed=1)


def test_invalid_container_path(pytester: pytest.Pytester) -> None:
    _write_ini(pytester, anydi_container="missing.module:container")
    pytester.makepyfile(test_any="def test_any(): pass")

    result = pytester.runpytest_subprocess()

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*anydi_container=missing.module:container*"])


def test_test_mode_off_after_session(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = Container()
    module = type(sys)("anydi_probe")
    module.__dict__["container"] = probe
    monkeypatch.setitem(sys.modules, "anydi_probe", module)
    _write_ini(pytester, anydi_container="anydi_probe:container")
    pytester.makepyfile(
        test_probe="""
        from anydi_probe import container


        def test_on():
            assert container._test_mode is True
        """
    )
    outer_global = get_global_container_or_none()

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)
    assert probe._test_mode is False
    assert get_global_container_or_none() is outer_global
