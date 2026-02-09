# AnyDI

Simple Dependency Injection library that uses Python type annotations.

<a href="https://github.com/python-anydi/anydi/actions/workflows/ci.yml">
    <img src="https://github.com/python-anydi/anydi/actions/workflows/ci.yml/badge.svg" alt="CI">
</a>
<a href="https://codecov.io/gh/python-anydi/anydi">
    <img src="https://codecov.io/gh/python-anydi/anydi/branch/main/graph/badge.svg" alt="Coverage">
</a>
<a href="https://anydi.readthedocs.io/en/stable/">
    <img src="https://readthedocs.org/projects/anydi/badge/?version=latest" alt="Documentation">
</a>

---

`AnyDI` is a simple Dependency Injection library for Python 3.10+. It works with sync and async applications and uses type annotations ([PEP 484](https://peps.python.org/pep-0484/)).

Main features:

* **Type-safe**: Uses type hints for dependency resolution.
* **Async support**: Works with both sync and async code.
* **Scopes**: Provides singleton, transient, and request scopes. Supports custom scope definitions.
* **Simple**: Minimal boilerplate with straightforward API.
* **Fast**: Low overhead dependency resolution.
* **Named providers**: Use `Annotated[...]` for multiple providers per type.
* **Resource management**: Context manager protocol support for lifecycle management.
* **Modular**: Container and module composition for large applications.
* **Auto-scan**: Automatic discovery of injectable callables.
* **Generic support**: Automatic TypeVar resolution for generic base classes.
* **Framework integrations**: Extensions for popular frameworks.
* **Testing**: Provider override mechanism for test isolation.

---

## Installation

```shell
pip install anydi
```

## Quick Example

### Define a Service (`app/services.py`)

```python
class GreetingService:
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"
```

### Create the Container and Providers (`app/container.py`)

```python
from anydi import Container

from app.services import GreetingService


container = Container()


@container.provider(scope="singleton")
def service() -> GreetingService:
    return GreetingService()
```

### Resolve Dependencies Directly

```python
from app.container import container
from app.services import GreetingService


service = container.resolve(GreetingService)

if __name__ == "__main__":
    print(service.greet("World"))
```

### Inject Into Functions (`app/main.py`)

```python
from anydi import Provide

from app.container import container
from app.services import GreetingService


def greet(service: Provide[GreetingService]) -> str:
    return service.greet("World")


if __name__ == "__main__":
    print(container.run(greet))
```

### Test with Overrides (`tests/test_app.py`)

```python
from unittest import mock

from app.container import container
from app.services import GreetingService
from app.main import greet


def test_greet() -> None:
    service_mock = mock.Mock(spec=GreetingService)
    service_mock.greet.return_value = "Mocked"

    with container.override(GreetingService, service_mock):
        result = container.run(greet)

    assert result == "Mocked"
```

### Integrate with FastAPI (`app/api.py`)

```python
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

### Test the FastAPI Integration (`test_api.py`)

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

    with container.override(GreetingService, service_mock):
        response = client.get("/greeting")

    assert response.json() == {"greeting": "Mocked"}
```

### Integrate with Django Ninja

Install the Django integration extras:

```shell
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
    ...
    "anydi_django",
]

ANYDI = {
    "CONTAINER_FACTORY": "app.container.container",
    "PATCH_NINJA": True,
}
```

Wire Django Ninja (`urls.py`):

```python
from typing import Any

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

## Learn More

Want to know more? Here are helpful resources:

**Core Documentation:**
- [Core Concepts](concepts.md) - Learn about containers, providers, scopes, and dependency injection
- [Providers](usage/providers/index.md) - How to register providers and manage resources
- [Scopes](usage/scopes.md) - How to use built-in and custom scopes
- [Dependency Injection](usage/injection.md) - Different ways to inject dependencies
- [Testing](usage/testing.md) - How to test your code with provider overrides

**Framework Integrations:**
- [FastAPI](extensions/fastapi.md) - How to use with FastAPI
- [Django](extensions/django.md) - How to use with Django and Django Ninja
- [FastStream](extensions/faststream.md) - How to use with message brokers
- [Typer](extensions/typer.md) - How to use in CLI applications
- [Pydantic Settings](extensions/pydantic_settings.md) - How to manage configuration
