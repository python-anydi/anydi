# Auto-Registration

`AnyDI` can auto-register dependencies without explicit registration. When you resolve a decorated class, the container automatically registers and resolves its entire dependency tree.

## Decorators

### `@provided`

The main decorator for auto-registration. Requires a `scope`:

```python
from anydi import Container, provided


@provided(scope="singleton")
class UserRepository:
    def find(self, id: int) -> dict:
        return {"id": id, "name": "Alice"}


container = Container()
repo = container.resolve(UserRepository)
```

### Shortcuts

`@singleton`, `@transient`, and `@request` are shortcuts:

| Decorator | Equivalent |
|-----------|------------|
| `@singleton` | `@provided(scope="singleton")` |
| `@transient` | `@provided(scope="transient")` |
| `@request` | `@provided(scope="request")` |

```python
from anydi import singleton, transient


@singleton
class Database:
    pass


@transient
class RequestHandler:
    pass
```

### Decoupled with `__provided__`

To avoid importing decorators, use the `__provided__` class variable:

```python
class UserRepository:
    __provided__ = {"scope": "singleton"}

    def find(self, id: int) -> dict:
        return {"id": id, "name": "Alice"}
```

Supported keys:

- `scope` (required): `"singleton"`, `"transient"`, or `"request"`
- `alias` (optional): type or list of types to register as
- `from_context` (optional): `True` for request-scoped context values

## Aliases

Use `alias` to make a class resolvable by an interface or base type:

```python
from abc import ABC, abstractmethod
from anydi import Container, singleton


class IRepository(ABC):
    @abstractmethod
    def find(self, id: int) -> dict:
        pass


@singleton(alias=IRepository)
class UserRepository(IRepository):
    def find(self, id: int) -> dict:
        return {"id": id, "name": "Alice"}


container = Container()
container.scan(["myapp.repositories"])

repo = container.resolve(UserRepository)   # By class
repo2 = container.resolve(IRepository)     # By interface
assert repo is repo2
```

Multiple aliases:

```python
@singleton(alias=[IReader, IWriter])
class CRUDRepository(IReader, IWriter):
    pass
```

!!! note
    The class is the primary registration. Aliases are additional keys resolving to the same instance. See [Type Aliases](basics.md#type-aliases).

## Request Scope with Context

Use `from_context=True` when the instance is set via `context.set()`:

```python
from anydi import Container, request


@request(from_context=True)
class Request:
    def __init__(self, path: str) -> None:
        self.path = path


container = Container()

with container.request_context() as ctx:
    ctx.set(Request, Request(path="/users"))
    req = container.resolve(Request)
    assert req.path == "/users"
```

## Generic TypeVar Resolution

`AnyDI` automatically resolves TypeVars when inheriting from generic base classes:

```python
from typing import Generic, TypeVar
from anydi import Container

T = TypeVar("T")


class User:
    pass


class Repository(Generic[T]):
    pass


class UserRepository(Repository[User]):
    pass


class Handler(Generic[T]):
    def __init__(self, repo: Repository[T]) -> None:
        self.repo = repo


class UserHandler(Handler[User]):
    pass  # No need to override __init__!


container = Container()
container.register(UserRepository, alias=Repository[User])
container.register(UserHandler)

handler = container.resolve(UserHandler)
assert isinstance(handler.repo, UserRepository)
```

This works with:

- Multi-level inheritance: `A[T] → B[T] → C[User]`
- Multiple type parameters: `Handler[T, U]` with partial specialization
- Nested generics: `list[Repository[T]]` → `list[Repository[User]]`

## Scanning

Use `scan()` to discover decorated classes at startup:

```python
from anydi import Container

container = Container()

# 1. Scan packages to find decorated classes
container.scan(["myapp.services", "myapp.repositories"])

# 2. Validate the dependency graph
container.build()

# 3. Use the container
service = container.resolve(MyService)
```

### Ignoring packages

Exclude packages from scanning:

```python
container.scan("myapp", ignore=["myapp.tests", "myapp.migrations"])
```

The `ignore` parameter accepts strings, module objects, or a mix of both.

### Relative paths

Use relative paths for portable configuration:

```python
# myapp/container.py
container.scan(".")                      # Current package
container.scan([".services", ".repos"])  # Submodules
container.scan(".", ignore=[".api"])     # Relative ignore
```

### Circular import detection

If a scanned module imports the container at module level, it triggers another `scan()` call. `AnyDI` detects this and raises `RuntimeError`.

**Solutions:**

- Use lazy imports inside functions
- Add problematic modules to `ignore`
- Keep container in a module that doesn't get scanned

## Mixing with Explicit Registration

Combine explicit and auto-registration:

```python
from anydi import Container, singleton


class EmailService:
    def send(self, to: str, message: str) -> None:
        print(f"Sending to {to}")


@singleton
class NotificationService:
    def __init__(self, email: EmailService) -> None:
        self.email = email


container = Container()
container.register(EmailService, scope="singleton")

# NotificationService auto-registers when resolved
notifier = container.resolve(NotificationService)
```

## Benefits

- **Less boilerplate**: No manual registration for every class
- **Maintainability**: Adding dependencies doesn't require updating registration
- **Flexibility**: Override specific dependencies while others auto-register

## Limitations

- **Explicit is better**: For public APIs, explicit registration provides better documentation
- **Circular dependencies**: Auto-registration cannot resolve circular dependencies
- **Scope validation**: Scope decorators must match usage patterns

---

**Related:**

- [Provider Basics](basics.md) - Explicit provider registration
- [Resource Management](resources.md) - Lifecycle of auto-registered resources
- [Scopes](../scopes.md) - Understanding scope decorators
