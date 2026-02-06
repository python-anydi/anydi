# Testing

## Test Mode

When overriding dependencies in tests, `AnyDI` uses a special **test mode** that enables proper override support throughout the dependency graph. Test mode ensures that overridden dependencies are correctly propagated to all dependent services.

### Enabling Test Mode

You can enable test mode in two ways:

**Using the context manager (recommended):**

```python
with container.test_mode():
    with container.override(Repository, mock_repo):
        # All resolutions here will use the override
        service = container.resolve(Service)
```

**Using explicit methods:**

```python
container.enable_test_mode()
try:
    with container.override(Repository, mock_repo):
        service = container.resolve(Service)
finally:
    container.disable_test_mode()
```

### Why Test Mode Matters

`AnyDI` compiles optimized resolvers for fast dependency resolution. Test mode switches to a separate set of resolvers that include override checking logic. This ensures:

- Overrides are checked at every resolution point
- Nested dependencies correctly receive overridden instances
- No performance impact in production (normal resolvers have no override checks)

**Note:** If you use the pytest plugin (see below), test mode is automatically enabled for you.

## Overriding Dependencies

Use the `.override(dependency_type, instance)` context manager to replace a dependency temporarily during testing. It helps you isolate code from its dependencies.
The `container.override()` works only inside the `with` block. When the block ends, the original dependency comes back.

```python
from dataclasses import dataclass
from unittest import mock

from anydi import Container, Inject


@dataclass(kw_only=True)
class Item:
    name: str


class Repository:
    def __init__(self) -> None:
        self.items: list[Item] = []

    def all(self) -> list[Item]:
        return self.items


class Service:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def get_items(self) -> list[Item]:
        return self.repo.all()


container = Container()


@container.inject
def get_items(service: Service = Inject()) -> list[Item]:
    return service.get_items()


def test_handler() -> None:
    repo_mock = mock.Mock(spec=Repository)
    repo_mock.all.return_value = [Item(name="mock1"), Item(name="mock2")]

    with container.test_mode():
        with container.override(Repository, repo_mock):
            assert get_items() == [Item(name="mock1"), Item(name="mock2")]
```

Or using nested context managers in a single `with` statement:

```python
def test_handler() -> None:
    repo_mock = mock.Mock(spec=Repository)
    repo_mock.all.return_value = [Item(name="mock1"), Item(name="mock2")]

    with container.test_mode(), container.override(Repository, repo_mock):
        assert get_items() == [Item(name="mock1"), Item(name="mock2")]
```

## Overriding Providers with Modules

You can create a testing module that overrides providers from your application modules. Use `@provider(scope="...", override=True)` to replace specific providers:

```python
from anydi import Container, Module, provider


class Database:
    def __init__(self, url: str) -> None:
        self.url = url


class UserService:
    def __init__(self, db: Database) -> None:
        self.db = db


class AppModule(Module):
    @provider(scope="singleton")
    def database(self) -> Database:
        return Database(url="postgresql://prod-server/db")

    @provider(scope="singleton")
    def user_service(self, db: Database) -> UserService:
        return UserService(db=db)


class TestingModule(Module):
    @provider(scope="singleton", override=True)
    def database(self) -> Database:
        return Database(url="sqlite:///:memory:")


# Setup container with both modules
container = Container()
container.register_module(AppModule())
container.register_module(TestingModule())

# UserService will use the overridden database from TestingModule
service = container.resolve(UserService)
assert service.db.url == "sqlite:///:memory:"
```

This approach is useful when you want to:

- Replace production dependencies with test doubles (e.g., in-memory databases)
- Override multiple providers in one place
- Share testing configuration across multiple test files

## Pytest Plugin

`AnyDI` has a pytest plugin that injects dependencies into test functions. This makes tests simpler and cleaner.

### Configuration

#### Container setup

You can provide a container for tests in two ways:

**Option 1: Use the `anydi_container` configuration**

Set the `anydi_container` option in your `pytest.ini` or `pyproject.toml`:

```ini
# pytest.ini
[pytest]
anydi_container = myapp.container:container
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
anydi_container = "myapp.container:container"
```

The configuration accepts:

- Container instances: `myapp.container:container` or `myapp.container.container`
- Factory functions: `myapp.container:create_container`

```python
# myapp/container.py
def create_container() -> Container:
    container = Container()
    # ... register providers
    return container
```

**Option 2: Define a `container` fixture**

Or define a `container` fixture in your test suite (e.g., in `conftest.py`):

```python
import pytest

from anydi import Container

from myapp import container as myapp_container


@pytest.fixture(scope="session")
def container() -> Container:
    return myapp_container
```

**Note:** The fixture takes priority over the configuration if both are defined.

### Usage

#### Explicit injection with `Provide[T]`

Use `Provide[T]` to mark parameters for injection from the container:

```python
from anydi import Container, Provide


def test_service_get_items(
    container: Container,
    service: Provide[Service],
) -> None:
    repo_mock = mock.Mock(spec=Repository)
    repo_mock.all.return_value = [Item(name="mock1"), Item(name="mock2")]

    with container.override(Repository, repo_mock):
        assert service.get_items() == [Item(name="mock1"), Item(name="mock2")]
```

Dependencies are resolved from the container based on type annotations.

### Auto-injection

Auto-injection is **enabled by default**. The plugin automatically injects any test parameter that matches a type registered in the container:

```python
def test_service(service: Service) -> None:
    assert service.get_items() == []
```

To disable auto-injection, set `anydi_autoinject = false`:

```ini
# pytest.ini
[pytest]
anydi_autoinject = false
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
anydi_autoinject = false
```

### Testing with `.create()`

For more control over dependency injection in tests, use the `.create()` method to instantiate classes with overridden dependencies:

```python
def test_handler(container: Container) -> None:
    repo_mock = mock.Mock(spec=Repository)
    repo_mock.all.return_value = [Item(name="mock1"), Item(name="mock2")]

    service = container.create(Service, repo=repo_mock)

    assert service.get_items() == [Item(name="mock1"), Item(name="mock2")]
```
