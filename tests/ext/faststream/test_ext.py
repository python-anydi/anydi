from typing import Any

import pytest
from faststream.redis import RedisBroker

from anydi import Container, Inject
from anydi.ext.faststream import install


def test_install_without_annotation() -> None:
    container = Container()

    @container.provider(scope="singleton")
    def message() -> str:
        return "Hello"

    broker = RedisBroker()

    @broker.subscriber("hello")
    def say_hello(message=Inject()) -> Any:  # type: ignore[no-untyped-def]
        return message

    with pytest.raises(
        TypeError, match=r"Missing `(.*?).say_hello` parameter `message` annotation."
    ):
        install(broker, container)


def test_install_unknown_annotation() -> None:
    container = Container()

    broker = RedisBroker()

    @broker.subscriber("hello")
    def say_hello(message: str = Inject()) -> Any:
        return message

    with pytest.raises(
        LookupError,
        match=(
            r"`(.*?).say_hello` has an unknown dependency parameter `message` "
            "with an annotation of `str`."
        ),
    ):
        install(broker, container)
