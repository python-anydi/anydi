from typing import Any

import pytest
import typer

from anydi import Container, Inject, Provide, singleton
from anydi.ext.typer import install


def test_install_without_annotation() -> None:
    container = Container()

    @container.provider(scope="singleton")
    def message() -> str:
        return "Hello"

    app = typer.Typer()

    @app.command()
    def say_hello(message=Inject()) -> Any:  # type: ignore[no-untyped-def]
        typer.echo(message)

    with pytest.raises(
        TypeError, match="Missing `(.*?).say_hello` parameter `message` annotation."
    ):
        install(app, container)


def test_install_unknown_annotation() -> None:
    container = Container()

    app = typer.Typer()

    @app.command()
    def say_hello(message: str = Inject()) -> Any:
        typer.echo(message)

    with pytest.raises(
        LookupError,
        match=(
            "`(.*?).say_hello` has an unknown dependency parameter `message` "
            "with an annotation of `str`."
        ),
    ):
        install(app, container)


def test_install_auto_provided() -> None:
    container = Container()

    @singleton
    class GreetingService:
        pass

    app = typer.Typer()

    @app.command()
    def say_hello(message: Provide[GreetingService]) -> Any:
        typer.echo(message)

    install(app, container)


def test_install_with_alias() -> None:
    """Test that install() correctly handles alias types."""

    class IService:
        pass

    class ServiceImpl(IService):
        pass

    container = Container()
    container.register(ServiceImpl, scope="singleton")
    container.alias(IService, ServiceImpl)

    app = typer.Typer()

    @app.command()
    def say_hello(service: IService = Inject()) -> Any:
        typer.echo(f"Service: {service}")

    # Should not raise - alias should be resolved to canonical type
    install(app, container)
