from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from fastapi import FastAPI, WebSocket
from starlette.middleware import Middleware
from starlette.testclient import TestClient

import anydi.ext.fastapi
from anydi import Container, Inject
from anydi.ext.starlette.middleware import RequestScopedMiddleware


def test_install_without_annotation() -> None:
    container = Container()

    @container.provider(scope="singleton")
    def message() -> str:
        return "Hello"

    app = FastAPI()

    @app.get("/hello")
    def say_hello(message=Inject()) -> Any:  # type: ignore[no-untyped-def]
        return message

    with pytest.raises(
        TypeError, match=r"Missing `(.*?).say_hello` parameter `message` annotation."
    ):
        anydi.ext.fastapi.install(app, container)


def test_install_unknown_annotation() -> None:
    container = Container()

    app = FastAPI()

    @app.get("/hello")
    def say_hello(message: str = Inject()) -> Any:
        return message

    with pytest.raises(
        LookupError,
        match=(
            r"`(.*?).say_hello` has an unknown dependency parameter `message` "
            "with an annotation of `str`."
        ),
    ):
        anydi.ext.fastapi.install(app, container)


def test_install_registers_websocket_scope() -> None:
    """Test that websocket scope is automatically registered during install."""
    # Create a fresh container without websocket scope
    container = Container()
    app = FastAPI()

    # Verify scope doesn't exist before install
    assert "websocket" not in container._scopes

    anydi.ext.fastapi.install(app, container)

    # Verify scope exists after install
    assert "websocket" in container._scopes


def test_install_websocket_resource_cleanup() -> None:
    """Test that websocket-scoped resources are properly cleaned up."""
    container = Container()
    container.register_scope("websocket", parents=["request"])
    cleanup_called: list[str] = []

    @container.provider(scope="websocket")
    def cleanup_resource() -> Iterator[str]:
        cleanup_called.append("setup")
        yield "resource"
        cleanup_called.append("cleanup")

    app = FastAPI(
        middleware=[
            Middleware(RequestScopedMiddleware, container=container),
        ]
    )

    @app.websocket("/ws/resource")
    async def websocket_resource(
        websocket: WebSocket,
        resource: Annotated[str, Inject()],
    ) -> None:
        await websocket.accept()
        await websocket.send_text(f"Got: {resource}")
        await websocket.close()

    # Install after defining routes so it can validate them
    anydi.ext.fastapi.install(app, container)

    client = TestClient(app)

    # Before connection
    assert cleanup_called == []

    # During connection
    with client.websocket_connect("/ws/resource") as websocket:
        response = websocket.receive_text()
        assert response == "Got: resource"
        # Setup called
        assert "setup" in cleanup_called

    # After connection closed
    assert cleanup_called == ["setup", "cleanup"]
