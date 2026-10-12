# AnyDI

<div style="text-align: center;">

Simple Dependency Injection library that uses Python type annotations.

[![CI](https://github.com/python-anydi/anydi/actions/workflows/ci.yml/badge.svg)](https://github.com/python-anydi/anydi/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/python-anydi/anydi/branch/main/graph/badge.svg)](https://codecov.io/gh/python-anydi/anydi)
[![Documentation](https://readthedocs.org/projects/anydi/badge/?version=latest)](https://anydi.readthedocs.io/en/stable/)
[![CodSpeed](https://img.shields.io/endpoint?url=https://codspeed.io/badge.json)](https://codspeed.io/python-anydi/anydi?utm_source=badge)

</div>

---
Documentation

http://anydi.readthedocs.io/

---

`AnyDI` is a simple Dependency Injection library for Python 3.11+. It works with sync and async applications and uses type annotations ([PEP 484](https://peps.python.org/pep-0484/)).

Main features:

* **Type-safe**: Uses type hints for dependency resolution.
* **Async support**: Works with both sync and async code.
* **Scopes**: Provides singleton, transient, and request scopes. Supports custom scope definitions.
* **Named providers**: Use `Annotated[...]` for multiple providers per type.
* **Resource management**: Context manager protocol support for lifecycle management.
* **Modular**: Container and module composition for large applications.
* **Auto-scan**: Automatic discovery of injectable callables.
* **Lazy references**: Module-level access to dependencies without injection.
* **Generic support**: Automatic TypeVar resolution for generic base classes.
* **Framework integrations**: Extensions for popular frameworks.
* **Testing**: Provider override mechanism for test isolation.

## Installation

```shell
pip install anydi
```

## Quick example

### Define a service (`app/services.py`)

```python
class GreetingService:
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"
```

### Create the container and providers (`app/container.py`)

```python
from anydi import Container

from app.services import GreetingService


container = Container()


@container.provider(scope="singleton")
def service() -> GreetingService:
    return GreetingService()
```

### Resolve dependencies directly

```python
from app.container import container
from app.services import GreetingService


service = container.resolve(GreetingService)

if __name__ == "__main__":
    print(service.greet("World"))
```

### Inject into functions (`app/main.py`)

```python
from anydi import Provide

from app.container import container
from app.services import GreetingService


def greet(service: Provide[GreetingService]) -> str:
    return service.greet("World")


if __name__ == "__main__":
    print(container.run(greet))
```

### Or use a lazy reference (`app/main.py`)

```python
from app.container import container
from app.services import GreetingService


service = container.ref(GreetingService)


def greet() -> str:
    return service.greet("World")


if __name__ == "__main__":
    print(greet())
```

The container owns the providers, scopes and lifespan either way. Injection and lazy references are two styles of reaching the same dependency.

### Test with overrides (`tests/test_app.py`)

```python
from unittest import mock

from app.container import container
from app.services import GreetingService
from app.main import greet


def test_greet() -> None:
    service_mock = mock.Mock(spec=GreetingService)
    service_mock.greet.return_value = "Mocked"

    with container.test_mode(), container.override(GreetingService, service_mock):
        result = container.run(greet)

    assert result == "Mocked"
```

### Integrate with FastAPI (`app/api.py`)

```python
from typing import Annotated

import anydi.ext.fastapi
from fastapi import FastAPI

from anydi import Provide
from app.container import container
from app.services import GreetingService


app = FastAPI()


@app.get("/greeting")
async def greet(
    service: Provide[GreetingService]
) -> dict[str, str]:
    return {"greeting": service.greet("World")}


anydi.ext.fastapi.install(app, container)
```

### Test the FastAPI integration (`test_api.py`)

```python
from unittest import mock

from fastapi.testclient import TestClient

from app.api import app
from app.container import container
from app.services import GreetingService


client = TestClient(app)


def test_api_greeting() -> None:
    service_mock = mock.Mock(spec=GreetingService)
    service_mock.greet.return_value = "Mocked"

    with container.test_mode(), container.override(GreetingService, service_mock):
        response = client.get("/greeting")

    assert response.json() == {"greeting": "Mocked"}
```

### Integrate with Django Ninja

Install the Django integration extras:

```sh
pip install 'anydi-django[ninja]'
```

Expose the container factory (`app/container.py`):

```python
from anydi import Container

from app.services import GreetingService


container = Container()


@container.provider(scope="singleton")
def service() -> GreetingService:
    return GreetingService()
```

Configure Django (`settings.py`):

```python
INSTALLED_APPS = [
    ...,
    "anydi_django",
]

ANYDI = {
    "CONTAINER_FACTORY": "app.container.container",
    "PATCH_NINJA": True,
}
```

Wire Django Ninja (`urls.py`):

```python
from typing import Annotated, Any

from anydi import Provide
from django.http import HttpRequest
from django.urls import path
from ninja import NinjaAPI

from app.services import GreetingService


api = NinjaAPI()


@api.get("/greeting")
def greet(request: HttpRequest, service: Provide[GreetingService]) -> Any:
    return {"greeting": service.greet("World")}


urlpatterns = [
    path("api/", api.urls),
]
```

## Documentation

**Guides:**
- [Getting started](https://anydi.readthedocs.io/en/stable/getting-started/)
- [Core Concepts](https://anydi.readthedocs.io/en/stable/concepts/)
- [Providers](https://anydi.readthedocs.io/en/stable/usage/providers/)
- [Scopes](https://anydi.readthedocs.io/en/stable/usage/scopes/)
- [Dependency Injection](https://anydi.readthedocs.io/en/stable/usage/injection/)
- [Testing](https://anydi.readthedocs.io/en/stable/usage/testing/)
- [Reference](https://anydi.readthedocs.io/en/stable/reference/)

**Framework integrations:**
- [FastAPI](https://anydi.readthedocs.io/en/stable/extensions/fastapi/)
- [Django](https://anydi.readthedocs.io/en/stable/extensions/django/)
- [FastStream](https://anydi.readthedocs.io/en/stable/extensions/faststream/)
- [Typer](https://anydi.readthedocs.io/en/stable/extensions/typer/)
- [Pydantic Settings](https://anydi.readthedocs.io/en/stable/extensions/pydantic_settings/)

**Everything else:**
- [Read the Docs](https://anydi.readthedocs.io/)
