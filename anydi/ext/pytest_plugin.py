from __future__ import annotations

import importlib.util
import inspect
import logging
from collections.abc import Generator
from typing import TYPE_CHECKING, Annotated, Any, cast, get_args, get_origin

import pytest
from typing_extensions import get_annotations

from anydi import (
    Container,
    import_container,
    reset_global_container,
    set_global_container,
)
from anydi._global import get_global_container_or_none, uses_global_container
from anydi._marker import is_marker

if TYPE_CHECKING:
    from _pytest.fixtures import SubRequest

logger = logging.getLogger(__name__)


CONTAINER = pytest.StashKey[Container]()
# Containers this plugin put into test mode, switched back off at session end
_ACTIVATED = pytest.StashKey[list[Container]]()
# The global container the plugin replaced, restored at session end
_REPLACED_GLOBAL = pytest.StashKey[Container | None]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "anydi",
        help=(
            "Wire the tests through the configured container: test mode, "
            "the `container` fixture, injection"
        ),
        type="bool",
        default=True,
    )
    parser.addini(
        "anydi_container",
        help=(
            "Path to container instance or factory "
            "(e.g., 'myapp.container:container' or 'myapp.container.container')"
        ),
        type="string",
        default=None,
    )
    parser.addini(
        "anydi_autoinject",
        help="Automatically inject dependencies into all test functions",
        type="bool",
        default=True,
    )


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    if not config.getini("anydi"):
        return
    config.stash[_ACTIVATED] = []
    container = _import_configured_container(config)
    if container is not None:
        _activate(config, container)
    config.pluginmanager.register(_AnydiPlugin(), "anydi-fixtures")


def pytest_unconfigure(config: pytest.Config) -> None:
    for container in config.stash.get(_ACTIVATED, []):
        container.disable_test_mode()
    if _REPLACED_GLOBAL in config.stash:
        reset_global_container()
        previous = config.stash[_REPLACED_GLOBAL]
        if previous is not None:
            set_global_container(previous)


class _AnydiPlugin:
    """Hooks and fixtures registered only when `anydi` is enabled."""

    @pytest.hookimpl(trylast=True)
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        # Collection has imported the application, so a global container
        # created there exists now, before any fixture can override it
        config = session.config
        container = config.stash.get(CONTAINER, None) or get_global_container_or_none()
        if container is not None:
            _activate(config, container)
            _use_as_global(config, container)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(
        self, fixturedef: pytest.FixtureDef[Any], request: SubRequest
    ) -> Generator[None]:
        """Enable test mode on a container provided by a `container` fixture."""
        yield
        if fixturedef.argname != "container" or fixturedef.cached_result is None:
            return
        container = fixturedef.cached_result[0]
        if not isinstance(container, Container):
            return
        if container is request.config.stash.get(CONTAINER, None):
            return
        container.enable_test_mode()
        # Let global references resolve against the container under test,
        # without introducing a global container the application never used
        if uses_global_container():
            reset_global_container()
            set_global_container(container)

    @pytest.fixture(scope="session")
    def container(self, request: pytest.FixtureRequest) -> Container:
        """Container fixture."""
        container = request.config.stash.get(CONTAINER, None)
        if container is not None:
            return container
        return _find_container(request)

    @pytest.fixture(autouse=True)
    def _anydi_inject(self, request: pytest.FixtureRequest) -> None:
        """Inject dependencies into sync test functions."""
        _inject(request)

    @pytest.fixture(autouse=True)
    def _anydi_ainject(self, request: pytest.FixtureRequest) -> None:
        """Inject dependencies into async test functions."""
        _ainject(request)


def _activate(config: pytest.Config, container: Container) -> None:
    """Put the container into test mode for the rest of the session."""
    config.stash[CONTAINER] = container
    # A container already in test mode belongs to whoever enabled it
    if not container._test_mode:
        container.enable_test_mode()
        config.stash[_ACTIVATED].append(container)


def _use_as_global(config: pytest.Config, container: Container) -> None:
    """Point global references at the container under test."""
    if not uses_global_container():
        return
    previous = get_global_container_or_none()
    if previous is container:
        return
    reset_global_container()
    set_global_container(container)
    config.stash.setdefault(_REPLACED_GLOBAL, previous)


def _inject(request: pytest.FixtureRequest) -> None:
    """Inject dependencies into sync test functions."""
    if inspect.iscoroutinefunction(request.function):
        return

    parameters = _get_injectable_params(request)
    if not parameters:
        return

    container = cast(Container, request.getfixturevalue("container"))

    for name, dependency_type in parameters:
        if not container.has_provider_for(dependency_type):
            continue
        try:
            request.node.funcargs[name] = container.resolve(dependency_type)
        except Exception:  # pragma: no cover
            logger.warning("Failed to resolve '%s' for %s", name, request.node.nodeid)


def _ainject(request: pytest.FixtureRequest) -> None:
    """Inject dependencies into async test functions."""
    if not inspect.iscoroutinefunction(
        request.function
    ) and not inspect.isasyncgenfunction(request.function):
        return

    parameters = _get_injectable_params(request)
    if not parameters:
        return

    if "anyio_backend" not in request.fixturenames:
        # ty mis-resolves pytest's `_with_exception`-decorated `fail` signature.
        pytest.fail(
            "To run async test functions with `anyio`, "  # ty: ignore[invalid-argument-type]
            "please configure the `anyio` pytest plugin.\n"
            "See: https://anyio.readthedocs.io/en/stable/testing.html",
            pytrace=False,  # ty: ignore[parameter-already-assigned]
        )

    container = cast(Container, request.getfixturevalue("container"))

    async def _resolve() -> None:
        for name, dependency_type in parameters:
            if not container.has_provider_for(dependency_type):
                continue
            try:
                request.node.funcargs[name] = await container.aresolve(dependency_type)
            except Exception:  # pragma: no cover
                logger.warning(
                    "Failed to resolve '%s' for %s", name, request.node.nodeid
                )

    # `anyio` keeps these out of its public API, so a version that renames them
    # breaks async injection only, not every test run that imports this plugin.
    try:
        from anyio.pytest_plugin import extract_backend_and_options, get_runner
    except ImportError:  # pragma: no cover - a version that moved them
        pytest.fail(
            "Injecting dependencies into async tests needs "  # ty: ignore[invalid-argument-type]
            "`extract_backend_and_options` and `get_runner` from "
            "`anyio.pytest_plugin`, which this version of `anyio` does not "
            "have. Resolve the dependency in the test instead, or report it.",
            pytrace=False,  # ty: ignore[parameter-already-assigned]
        )

    anyio_backend = request.getfixturevalue("anyio_backend")
    backend_name, backend_options = extract_backend_and_options(anyio_backend)

    with get_runner(backend_name, backend_options) as runner:
        runner.run_fixture(_resolve, {})


def _get_injectable_params(
    request: pytest.FixtureRequest,
) -> list[tuple[str, Any]]:
    """Get injectable parameters for a test function."""
    fixture_names = set(request.node._fixtureinfo.initialnames) - set(
        request.node._fixtureinfo.name2fixturedefs.keys()
    )

    autoinject = cast(bool, request.config.getini("anydi_autoinject"))

    has_any_explicit = False
    explicit_params: list[tuple[str, Any]] = []
    all_params: list[tuple[str, Any]] = []

    annotations = get_annotations(request.function, eval_str=True)

    for name, annotation in annotations.items():
        if name in ("request", "return"):
            continue

        dependency_type, is_explicit = _extract_dependency_type(annotation)

        if is_explicit:
            has_any_explicit = True
            explicit_params.append((name, dependency_type))
        elif name in fixture_names:
            all_params.append((name, dependency_type))

    # Priority: explicit markers > autoinject
    if has_any_explicit:
        return explicit_params
    if autoinject:
        return all_params
    return []


def _extract_dependency_type(annotation: Any) -> tuple[Any, bool]:
    """Extract the actual type and whether it has an explicit injection marker.

    Handles Provide[T] and Annotated[T, Inject()].
    Returns (unwrapped_type, is_explicit).
    """
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        for arg in args[1:]:
            if is_marker(arg):
                return args[0], True
    return annotation, False


def _import_configured_container(config: pytest.Config) -> Container | None:
    """Import the container named by `anydi_container`, if set."""
    container_path = cast(str | None, config.getini("anydi_container"))
    if not container_path:
        return None
    try:
        return import_container(container_path)
    except ImportError as exc:
        raise pytest.UsageError(
            f"Failed to load container from config "
            f"'anydi_container={container_path}': {exc}"
        ) from exc


def _detect_container(config: pytest.Config) -> Container | None:
    """Find the container from config, the global one or `anydi_django`."""
    container = _import_configured_container(config)
    if container is not None:
        return container

    global_container = get_global_container_or_none()
    if global_container is not None:
        return global_container

    pluginmanager = config.pluginmanager
    if pluginmanager.hasplugin("django") and importlib.util.find_spec("anydi_django"):
        return import_container("anydi_django.container")
    return None


def _find_container(request: pytest.FixtureRequest) -> Container:
    """Find container from config or auto-detection."""
    container = _detect_container(request.config)
    if container is not None:
        return container

    raise pytest.FixtureLookupError(
        None,
        request,
        "`container` fixture is not found and 'anydi_container' config is not set. "
        "Either define a `container` fixture in your test module, create a global "
        "container or set 'anydi_container' in pytest.ini.",
    )
