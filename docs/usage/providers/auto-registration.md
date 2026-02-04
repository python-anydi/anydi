# Auto-Registration

`AnyDI` can auto-register dependencies without explicit registration. It resolves and registers dependencies dynamically, which simplifies configuration when you have many classes to register.

## Basic Auto-Registration

Consider a scenario with class dependencies:

```python
from anydi import singleton


@singleton
class Database:
    def connect(self) -> None:
        print("Connecting to database")

    def disconnect(self) -> None:
        print("Disconnecting from database")


@singleton
class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def find_user(self, user_id: int) -> dict:
        return {"id": user_id, "name": "Alice"}


@singleton
class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    def get_user(self, user_id: int) -> dict:
        return self.repo.find_user(user_id)
```

You can instantiate these classes without manual registration. Register the root dependency (if needed) and the container will resolve the entire dependency tree automatically:

```python
from typing import Iterator

from anydi import Container

container = Container()


# Only register the Database with lifecycle management
@container.provider(scope="singleton")
def db() -> Iterator[Database]:
    db = Database()
    db.connect()
    yield db
    db.disconnect()


# Resolve UserService - Repository and Service are auto-registered
service = container.resolve(UserService)
user = service.get_user(123)

# Verify all dependencies were auto-registered
assert container.is_resolved(UserService)
assert container.is_resolved(UserRepository)
assert container.is_resolved(Database)
```

## Scope decorators

### `@provided` decorator

The main decorator for auto-registration. Requires `scope`:

```python
from anydi import Container, provided


@provided(scope="singleton")
class UserRepository:
    def find(self, id: int) -> dict:
        return {"id": id, "name": "Alice"}


container = Container()
repo = container.resolve(UserRepository)
```

### Shortcut decorators

`@singleton`, `@transient`, and `@request` are shortcuts for `@provided`:

| Shortcut | Equivalent |
|----------|------------|
| `@singleton` | `@provided(scope="singleton")` |
| `@transient` | `@provided(scope="transient")` |
| `@request` | `@provided(scope="request")` |

### Register with an `alias`

Use `alias` to make a class resolvable by an interface or base type. This works with `container.scan()`:

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

# Resolve by class (primary)
repo = container.resolve(UserRepository)

# Resolve by interface (alias)
repo2 = container.resolve(IRepository)
assert repo is repo2  # Same instance
```

All decorators support `alias` (single or list):

```python
# Single alias
@singleton(alias=IRepository)
class UserRepository(IRepository):
    pass

# Multiple aliases
@singleton(alias=[IReader, IWriter, IDeleter])
class CRUDRepository(IReader, IWriter, IDeleter):
    pass
```

!!! note "Alias Semantics"
    The class is the primary registration. Aliases are additional keys that resolve to the same instance. See [Type Aliases](basics.md#type-aliases) for more details.

### `@request` with `from_context`

Use `from_context=True` when instance is set via `context.set()`:

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

## Decoupled registration with `__provided__`

If you want to avoid importing `anydi` decorators in your classes, use the `__provided__` class variable directly:

```python
class UserRepository:
    __provided__ = {"scope": "singleton"}

    def find(self, id: int) -> dict:
        return {"id": id, "name": "Alice"}
```

This keeps your classes free from framework imports. The `__provided__` dict supports:

- `scope` (required) - `"singleton"`, `"transient"`, or `"request"`
- `alias` (optional) - the type to register as, e.g., a base class or protocol (works with `scan()`)
- `from_context` (optional) - `True` if set via `context.set()`, only for `"request"` scope

## Mixing explicit and auto-registration

You can combine explicit registration with auto-registration:

```python
from anydi import Container, singleton


class EmailService:
    def send(self, to: str, message: str) -> None:
        print(f"Sending email to {to}: {message}")


@singleton
class NotificationService:
    def __init__(self, email: EmailService) -> None:
        self.email = email

    def notify(self, user: str, message: str) -> None:
        self.email.send(user, message)


container = Container()

# Explicitly register EmailService
container.register(EmailService, scope="singleton")

# NotificationService will be auto-registered when resolved
notifier = container.resolve(NotificationService)
notifier.notify("user@example.com", "Welcome!")
```

## Benefits of auto-registration

1. **Less boilerplate**: No need to register every class manually in dependency tree
2. **Maintainability**: Adding new dependencies doesn't require updating registration code
3. **Flexibility**: Can override specific dependencies while others auto-register

## Generic inheritance support

`AnyDI` automatically resolves TypeVars when a class inherits from a generic base class. This means you don't need to redefine the constructor just to specify concrete types.

```python
from anydi import Container, singleton


class User:
    pass


class Repository[T]:
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

# AnyDI resolves Repository[T] → Repository[User] automatically
handler = container.resolve(UserHandler)
assert isinstance(handler.repo, UserRepository)
```

This works with:

- **Multi-level inheritance**: `A[T] → B[T] → C[User]`
- **Multiple type parameters**: `Handler[T, U]` with partial specialization
- **Nested generics**: `list[Repository[T]]` → `list[Repository[User]]`

Without this feature, you would need to override the constructor in every subclass:

```python
# Before: verbose and repetitive
class UserHandler(Handler["User"]):
    def __init__(self, repo: Repository["User"]) -> None:
        super().__init__(repo)


# After: just inherit!
class UserHandler(Handler["User"]):
    pass
```

## Limitations

1. **Explicit is better**: For public APIs or library public APIs, explicit registration gives better documentation
2. **Circular dependencies**: Auto-registration cannot resolve circular dependencies
3. **Scope validation**: The scope decorator must match the usage pattern

## Scanning and build

`AnyDI` can find and register classes automatically when they are needed. However, it's better to use the `scan()` method to find all decorated classes when your application starts.

If you use `build()` to check your dependencies for errors, you should call `scan()` **before** `build()`. This makes sure the container knows about all your decorated classes.

```python
from anydi import Container

container = Container()

# 1. Scan packages to find @provided classes
container.scan(["myapp.services", "myapp.repositories"])

# 2. Build and check the dependency graph
container.build()

# 3. Use the container
service = container.resolve(MyService)
```

By calling `scan()` before `build()`, `AnyDI` can:
- Find all classes with decorators like `@singleton` or `@request`.
- Check that all dependencies exist.
- Find circular dependencies or scope problems at startup.

### Ignoring packages

Use the `ignore` parameter to exclude specific packages or modules from scanning. This is useful to:

- **Avoid circular imports** - when modules have complex import dependencies
- **Prevent infinite loops** - when scanning would trigger problematic module loading
- **Exclude test/migration code** - keep test fixtures and database migrations out of production container

```python
from anydi import Container

container = Container()

# Scan myapp but ignore the tests subpackage
container.scan("myapp", ignore=["myapp.tests"])

# Ignore multiple packages
container.scan("myapp", ignore=["myapp.tests", "myapp.migrations"])

# Ignore using module objects
import myapp.tests
container.scan("myapp", ignore=[myapp.tests])
```

The `ignore` parameter accepts:
- A single string: `ignore="myapp.tests"`
- A list of strings: `ignore=["myapp.tests", "myapp.migrations"]`
- Module objects: `ignore=[myapp.tests]`
- Mixed: `ignore=["myapp.tests", some_module]`

When a package is ignored, all its submodules are also ignored.

### Relative package paths

You can use relative paths (like Python's relative imports) for more portable configuration:

```python
# myapp/container.py
container.scan(".")                      # Scan current package (myapp)
container.scan([".services", ".repos"])  # Scan submodules
container.scan(".", ignore=[".api"])     # Relative ignore paths
container.scan("..")                     # Scan parent package
container.scan("..other")                # Scan sibling package
```

### Circular import detection

If a scanned module imports the container at module level, it can trigger another `scan()` call, creating an infinite loop. `AnyDI` detects this and raises a `RuntimeError` with a helpful message.

```python
# myapp/services.py - this module is being scanned
from myapp.container import container  # <- triggers scan() again, causing loop

@singleton
class MyService:
    pass
```

**Solutions:**

- **Use lazy imports** - import container inside functions, not at module level
- **Use the ignore list**: `container.scan("myapp", ignore=["myapp.services"])`
- **Separate container definition** - keep container in a module that doesn't get scanned

---

**Related Topics:**
- [Provider Basics](basics.md) - Learn explicit provider registration
- [Resource Management](resources.md) - Manage lifecycle of auto-registered resources
- [Scopes](../scopes.md) - Understand scope decorators
