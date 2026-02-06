from __future__ import annotations

import importlib.util
import inspect
import logging
from collections.abc import Generator
from typing import TYPE_CHECKING, Annotated, Any, cast, get_args, get_origin

import pytest
from anyio.pytest_plugin import extract_backend_and_options, get_runner
from typing_extensions import get_annotations

from anydi import Container, import_container
from anydi._marker import is_marker

if TYPE_CHECKING:
    from _pytest.fixtures import SubRequest

logger = logging.getLogger(__name__)


def pytest_addoption(parser: pytest.Parser) -> None:
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


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[Any], request: SubRequest
) -> Generator[None]:
    """Automatically enable test mode on the container fixture."""
    yield
    if fixturedef.argname == "container" and fixturedef.cached_result is not None:
        container = fixturedef.cached_result[0]
        if isinstance(container, Container):
            container.enable_test_mode()


@pytest.fixture(scope="session")
def container(request: pytest.FixtureRequest) -> Container:
    """Container fixture."""
    return _find_container(request)


@pytest.fixture(autouse=True)
def _anydi_inject(request: pytest.FixtureRequest) -> None:
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


@pytest.fixture(autouse=True)
def _anydi_ainject(request: pytest.FixtureRequest) -> None:
    """Inject dependencies into async test functions."""
    if not inspect.iscoroutinefunction(
        request.function
    ) and not inspect.isasyncgenfunction(request.function):
        return

    parameters = _get_injectable_params(request)
    if not parameters:
        return

    if "anyio_backend" not in request.fixturenames:
        pytest.fail(
            "To run async test functions with `anyio`, "
            "please configure the `anyio` pytest plugin.\n"
            "See: https://anyio.readthedocs.io/en/stable/testing.html",
            pytrace=False,
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


def _find_container(request: pytest.FixtureRequest) -> Container:
    """Find container from config or auto-detection."""
    container_path = cast(str | None, request.config.getini("anydi_container"))
    if container_path:
        try:
            return import_container(container_path)
        except ImportError as exc:
            raise RuntimeError(
                f"Failed to load container from config "
                f"'anydi_container={container_path}': {exc}"
            ) from exc

    pluginmanager = request.config.pluginmanager
    if pluginmanager.hasplugin("django") and importlib.util.find_spec("anydi_django"):
        return import_container("anydi_django.container")

    raise pytest.FixtureLookupError(
        None,
        request,
        "`container` fixture is not found and 'anydi_container' config is not set. "
        "Either define a `container` fixture in your test module "
        "or set 'anydi_container' in pytest.ini.",
    )
