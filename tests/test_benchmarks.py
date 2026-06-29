import sys

import anyio
import pytest
from pytest_codspeed import BenchmarkFixture

if "--codspeed" not in sys.argv:
    pytest.skip(
        "Benchmark tests are skipped by default; run with --codspeed.",  # ty: ignore[too-many-positional-arguments]
        allow_module_level=True,
    )

from anydi import Container, Inject


class Config:
    __slots__ = ("message",)

    def __init__(self) -> None:
        self.message = "hello world"


class Repository:
    def __init__(self, config: Config) -> None:
        self._config = config

    def read(self) -> str:
        return self._config.message


class Service:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def handle(self) -> str:
        return self._repository.read()


class UseCase:
    def __init__(self, service: Service) -> None:
        self._service = service

    def execute(self) -> str:
        return self._service.handle()


class Controller:
    def __init__(self, use_case: UseCase) -> None:
        self._use_case = use_case

    def run(self) -> str:
        return self._use_case.execute()


class Handler:
    def __init__(self, controller: Controller) -> None:
        self._controller = controller

    def handle(self) -> str:
        return self._controller.run()


class Middleware:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler

    def process(self) -> str:
        return self._handler.handle()


class Gateway:
    def __init__(self, middleware: Middleware) -> None:
        self._middleware = middleware

    def execute(self) -> str:
        return self._middleware.process()


class Facade:
    def __init__(self, gateway: Gateway) -> None:
        self._gateway = gateway

    def run(self) -> str:
        return self._gateway.execute()


class Application:
    def __init__(self, facade: Facade) -> None:
        self._facade = facade

    def start(self) -> str:
        return self._facade.run()


@pytest.fixture
def container_singleton():  # noqa: C901
    container = Container()

    @container.provider(scope="singleton")
    def provide_config() -> Config:
        return Config()

    @container.provider(scope="singleton")
    def provide_repository(config: Config) -> Repository:
        return Repository(config)

    @container.provider(scope="singleton")
    def provide_service(repository: Repository) -> Service:
        return Service(repository)

    @container.provider(scope="singleton")
    def provide_use_case(service: Service) -> UseCase:
        return UseCase(service)

    @container.provider(scope="singleton")
    def provide_controller(use_case: UseCase) -> Controller:
        return Controller(use_case)

    @container.provider(scope="singleton")
    def provide_handler(controller: Controller) -> Handler:
        return Handler(controller)

    @container.provider(scope="singleton")
    def provide_middleware(handler: Handler) -> Middleware:
        return Middleware(handler)

    @container.provider(scope="singleton")
    def provide_gateway(middleware: Middleware) -> Gateway:
        return Gateway(middleware)

    @container.provider(scope="singleton")
    def provide_facade(gateway: Gateway) -> Facade:
        return Facade(gateway)

    @container.provider(scope="singleton")
    def provide_application(facade: Facade) -> Application:
        return Application(facade)

    container.start()
    yield container
    container.close()


@pytest.fixture
def container_transient():  # noqa: C901
    container = Container()

    @container.provider(scope="transient")
    def provide_config() -> Config:
        return Config()

    @container.provider(scope="transient")
    def provide_repository(config: Config) -> Repository:
        return Repository(config)

    @container.provider(scope="transient")
    def provide_service(repository: Repository) -> Service:
        return Service(repository)

    @container.provider(scope="transient")
    def provide_use_case(service: Service) -> UseCase:
        return UseCase(service)

    @container.provider(scope="transient")
    def provide_controller(use_case: UseCase) -> Controller:
        return Controller(use_case)

    @container.provider(scope="transient")
    def provide_handler(controller: Controller) -> Handler:
        return Handler(controller)

    @container.provider(scope="transient")
    def provide_middleware(handler: Handler) -> Middleware:
        return Middleware(handler)

    @container.provider(scope="transient")
    def provide_gateway(middleware: Middleware) -> Gateway:
        return Gateway(middleware)

    @container.provider(scope="transient")
    def provide_facade(gateway: Gateway) -> Facade:
        return Facade(gateway)

    @container.provider(scope="transient")
    def provide_application(facade: Facade) -> Application:
        return Application(facade)

    return container


@pytest.fixture
def container_request():  # noqa: C901
    container = Container()

    @container.provider(scope="request")
    def provide_config() -> Config:
        return Config()

    @container.provider(scope="request")
    def provide_repository(config: Config) -> Repository:
        return Repository(config)

    @container.provider(scope="request")
    def provide_service(repository: Repository) -> Service:
        return Service(repository)

    @container.provider(scope="request")
    def provide_use_case(service: Service) -> UseCase:
        return UseCase(service)

    @container.provider(scope="request")
    def provide_controller(use_case: UseCase) -> Controller:
        return Controller(use_case)

    @container.provider(scope="request")
    def provide_handler(controller: Controller) -> Handler:
        return Handler(controller)

    @container.provider(scope="request")
    def provide_middleware(handler: Handler) -> Middleware:
        return Middleware(handler)

    @container.provider(scope="request")
    def provide_gateway(middleware: Middleware) -> Gateway:
        return Gateway(middleware)

    @container.provider(scope="request")
    def provide_facade(gateway: Gateway) -> Facade:
        return Facade(gateway)

    @container.provider(scope="request")
    def provide_application(facade: Facade) -> Application:
        return Application(facade)

    return container


def test_benchmark_singleton_scope(
    benchmark: BenchmarkFixture, container_singleton: Container
) -> None:
    """Benchmark singleton scope resolution."""

    def resolve() -> str:
        return container_singleton.resolve(Application).start()

    result = benchmark(resolve)
    assert result == "hello world"


def test_benchmark_transient_scope(
    benchmark: BenchmarkFixture, container_transient: Container
) -> None:
    """Benchmark transient scope resolution."""

    def resolve() -> str:
        return container_transient.resolve(Application).start()

    result = benchmark(resolve)
    assert result == "hello world"


def test_benchmark_request_scope(
    benchmark: BenchmarkFixture, container_request: Container
) -> None:
    """Benchmark request scope resolution."""

    def resolve() -> str:
        with container_request.request_context():
            return container_request.resolve(Application).start()

    result = benchmark(resolve)
    assert result == "hello world"


def test_benchmark_singleton_scope_async(
    benchmark: BenchmarkFixture, container_singleton: Container
) -> None:
    """Benchmark singleton scope async resolution."""

    async def resolve() -> str:
        return (await container_singleton.aresolve(Application)).start()

    result = benchmark(lambda: anyio.run(resolve))
    assert result == "hello world"


def test_benchmark_transient_scope_async(
    benchmark: BenchmarkFixture, container_transient: Container
) -> None:
    """Benchmark transient scope async resolution."""

    async def resolve() -> str:
        return (await container_transient.aresolve(Application)).start()

    result = benchmark(lambda: anyio.run(resolve))
    assert result == "hello world"


def test_benchmark_request_scope_async(
    benchmark: BenchmarkFixture, container_request: Container
) -> None:
    """Benchmark request scope async resolution."""

    async def resolve() -> str:
        async with container_request.arequest_context():
            return (await container_request.aresolve(Application)).start()

    result = benchmark(lambda: anyio.run(resolve))
    assert result == "hello world"


def test_benchmark_inject_singleton(
    benchmark: BenchmarkFixture, container_singleton: Container
) -> None:
    """Benchmark function injection with singleton scope."""

    @container_singleton.inject
    def process(app: Application = Inject()) -> str:
        return app.start()

    result = benchmark(process)
    assert result == "hello world"


def test_benchmark_inject_transient(
    benchmark: BenchmarkFixture, container_transient: Container
) -> None:
    """Benchmark function injection with transient scope."""

    @container_transient.inject
    def process(app: Application = Inject()) -> str:
        return app.start()

    result = benchmark(process)
    assert result == "hello world"


def test_benchmark_inject_request(
    benchmark: BenchmarkFixture, container_request: Container
) -> None:
    """Benchmark function injection with request scope."""

    @container_request.inject
    def process(app: Application = Inject()) -> str:
        return app.start()

    with container_request.request_context():
        result = benchmark(process)
        assert result == "hello world"


def test_benchmark_inject_singleton_async(
    benchmark: BenchmarkFixture, container_singleton: Container
) -> None:
    """Benchmark async function injection with singleton scope."""

    @container_singleton.inject
    async def process(app: Application = Inject()) -> str:
        return app.start()

    result = benchmark(lambda: anyio.run(process))
    assert result == "hello world"


def test_benchmark_inject_transient_async(
    benchmark: BenchmarkFixture, container_transient: Container
) -> None:
    """Benchmark async function injection with transient scope."""

    @container_transient.inject
    async def process(app: Application = Inject()) -> str:
        return app.start()

    result = benchmark(lambda: anyio.run(process))
    assert result == "hello world"


def test_benchmark_inject_request_async(
    benchmark: BenchmarkFixture, container_request: Container
) -> None:
    """Benchmark async function injection with request scope."""

    @container_request.inject
    async def process(app: Application = Inject()) -> str:
        return app.start()

    async def run_in_context() -> str:
        async with container_request.arequest_context():
            return await process()

    result = benchmark(lambda: anyio.run(run_in_context))
    assert result == "hello world"
