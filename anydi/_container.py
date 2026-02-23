"""AnyDI core implementation module."""

from __future__ import annotations

import contextlib
import importlib
import inspect
import logging
import types
import uuid
import warnings
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Sequence
from contextvars import ContextVar
from typing import Any, Literal, TypeVar, cast, get_args, get_origin, overload

from typing_extensions import ParamSpec, Self, type_repr

from ._context import InstanceContext
from ._decorators import is_provided
from ._generics import build_typevar_map, resolve_typevars
from ._graph import Graph
from ._injector import Injector
from ._marker import Marker
from ._module import ModuleDef, ModuleRegistrar
from ._provider import Provider, ProviderDef, ProviderKind, ProviderParameter
from ._resolver import Resolver
from ._scanner import PackageOrIterable, Scanner
from ._types import (
    NOT_SET,
    Event,
    Scope,
    is_event_type,
    is_iterator_type,
    is_none_type,
    to_list,
)

T = TypeVar("T", bound=Any)
P = ParamSpec("P")


class Container:
    """AnyDI is a dependency injection container."""

    def __init__(
        self,
        *,
        providers: Iterable[ProviderDef] | None = None,
        modules: Iterable[ModuleDef] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._providers: dict[Any, Provider] = {}
        self._logger = logger or logging.getLogger(__name__)
        self._scopes: dict[str, Sequence[str]] = {
            "transient": ("transient", "singleton"),
            "singleton": ("singleton",),
        }

        self._resources: dict[str, list[Any]] = defaultdict(list)
        self._aliases: dict[Any, Any] = {}  # alias_type → canonical_type
        self._aliases_by_canonical: dict[Any, set[Any]] = defaultdict(set)
        self._singleton_context = InstanceContext()
        self._scoped_context: dict[str, ContextVar[InstanceContext]] = {}

        # Components
        self._resolver = Resolver(self)
        self._injector = Injector(self)
        self._modules = ModuleRegistrar(self)
        self._scanner = Scanner(self)
        self._graph = Graph(self)

        # Build state
        self._ready = False

        # Test mode (enables override support for all resolutions)
        self._test_mode = False

        # Register default scopes
        self.register_scope("request")

        # Register self as provider
        self.register(Container, lambda: self, scope="singleton")

        # Register providers
        providers = providers or []
        for provider in providers:
            self.register(
                provider.dependency_type,
                provider.factory,
                scope=provider.scope,
                from_context=provider.from_context,
                alias=provider.alias,
                override=False,
            )

        # Register modules
        modules = modules or []
        for module in modules:
            self.register_module(module)

    # == Container Properties ==

    @property
    def providers(self) -> dict[type[Any], Provider]:
        """Get the registered providers."""
        return self._providers

    @property
    def aliases(self) -> dict[Any, Any]:
        """Get the registered aliases."""
        return self._aliases

    @property
    def ready(self) -> bool:
        """Check if the container is ready."""
        return self._ready

    @property
    def logger(self) -> logging.Logger:
        """Get the logger instance."""
        return self._logger

    # == Context & Lifespan Management ==

    def __enter__(self) -> Self:
        """Enter the singleton context."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> Any:
        """Exit the singleton context."""
        return self._singleton_context.__exit__(exc_type, exc_val, exc_tb)

    def start(self) -> None:
        """Start the singleton context."""
        # Resolve all singleton resources
        for dependency_type in self._resources.get("singleton", []):
            self.resolve(dependency_type)

    def close(self) -> None:
        """Close the singleton context."""
        self._singleton_context.close()

    async def __aenter__(self) -> Self:
        """Enter the singleton context."""
        await self.astart()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        """Exit the singleton context."""
        return await self._singleton_context.__aexit__(exc_type, exc_val, exc_tb)

    async def astart(self) -> None:
        """Start the singleton context asynchronously."""
        for dependency_type in self._resources.get("singleton", []):
            await self.aresolve(dependency_type)

    async def aclose(self) -> None:
        """Close the singleton context asynchronously."""
        await self._singleton_context.aclose()

    @contextlib.contextmanager
    def scoped_context(self, scope: str) -> Iterator[InstanceContext]:
        """Obtain a context manager for the request-scoped context."""
        context_var = self._get_scoped_context_var(scope)

        # Check if context already exists (re-entering same scope)
        context = context_var.get(None)
        if context is not None:
            # Reuse existing context, don't create a new one
            yield context
            return

        # Create new context
        context = InstanceContext()
        token = context_var.set(context)

        # Resolve all request resources
        for dependency_type in self._resources.get(scope, []):
            if not is_event_type(dependency_type):
                continue
            self.resolve(dependency_type)

        with context:
            yield context
            context_var.reset(token)

    @contextlib.asynccontextmanager
    async def ascoped_context(self, scope: str) -> AsyncIterator[InstanceContext]:
        """Obtain a context manager for the specified scoped context."""
        context_var = self._get_scoped_context_var(scope)

        # Check if context already exists (re-entering same scope)
        context = context_var.get(None)
        if context is not None:
            # Reuse existing context, don't create a new one
            yield context
            return

        # Create new context
        context = InstanceContext()
        token = context_var.set(context)

        # Resolve all request resources
        for dependency_type in self._resources.get(scope, []):
            if not is_event_type(dependency_type):
                continue
            await self.aresolve(dependency_type)

        async with context:
            yield context
            context_var.reset(token)

    @contextlib.contextmanager
    def request_context(self) -> Iterator[InstanceContext]:
        """Obtain a context manager for the request-scoped context."""
        with self.scoped_context("request") as context:
            yield context

    @contextlib.asynccontextmanager
    async def arequest_context(self) -> AsyncIterator[InstanceContext]:
        """Obtain an async context manager for the request-scoped context."""
        async with self.ascoped_context("request") as context:
            yield context

    def _get_scoped_context(self, scope: str) -> InstanceContext:
        scoped_context_var = self._get_scoped_context_var(scope)
        try:
            scoped_context = scoped_context_var.get()
        except LookupError as exc:
            raise LookupError(
                f"The {scope} context has not been started. Please ensure that "
                f"the {scope} context is properly initialized before attempting "
                "to use it."
            ) from exc
        return scoped_context

    def _get_scoped_context_var(self, scope: str) -> ContextVar[InstanceContext]:
        """Get the context variable for the specified scope."""
        # Validate that scope is registered and not reserved
        if scope in ("transient", "singleton"):
            raise ValueError(
                f"Cannot get context variable for reserved scope `{scope}`."
            )
        if scope not in self._scopes:
            raise ValueError(
                f"Cannot get context variable for not registered scope `{scope}`. "
                f"Please register the scope first using register_scope()."
            )

        if scope not in self._scoped_context:
            self._scoped_context[scope] = ContextVar(f"{scope}_context")
        return self._scoped_context[scope]

    def _get_instance_context(self, scope: Scope) -> InstanceContext:
        """Get the instance context for the specified scope."""
        if scope == "singleton":
            return self._singleton_context
        return self._get_scoped_context(scope)

    # == Scopes == #

    def register_scope(
        self, scope: str, *, parents: Sequence[str] | None = None
    ) -> None:
        """Register a new scope with the specified parents."""
        # Check if the scope is reserved
        if scope in ("transient", "singleton"):
            raise ValueError(
                f"The scope `{scope}` is reserved and cannot be overridden."
            )

        # Check if the scope is already registered
        if scope in self._scopes:
            raise ValueError(f"The scope `{scope}` is already registered.")

        # Validate parents
        parents = parents or []
        for parent in parents:
            if parent not in self._scopes:
                raise ValueError(f"The parent scope `{parent}` is not registered.")

        # Register the scope
        self._scopes[scope] = tuple({scope, "singleton"} | set(parents))

    def has_scope(self, scope: str) -> bool:
        """Check if a scope is registered."""
        return scope in self._scopes

    def get_context_scopes(self, scopes: set[Scope] | None = None) -> list[str]:  # noqa: C901
        """Return scopes that require context management in dependency order."""
        # Build execution order: singleton -> request -> custom (by depth)
        ordered = ["singleton"]
        custom_scopes: list[tuple[int, str]] = []
        has_request = False

        for scope, parents in self._scopes.items():
            if scope == "singleton":
                continue
            if scope == "request":
                has_request = True
                continue
            if scope == "transient":
                continue
            custom_scopes.append((len(parents), scope))

        if has_request:
            ordered.append("request")

        custom_scopes.sort(key=lambda item: item[0])
        ordered.extend(scope for _, scope in custom_scopes)

        # If no filter, return all scopes with contexts (transient excluded)
        if scopes is None:
            return ordered

        # Helper to add scope with its parents to needed set
        def add_scope_tree(needed: set[str], scope: str) -> None:
            if scope == "singleton":
                needed.add("singleton")
            elif scope != "transient":
                needed.update(self._scopes[scope])

        needed_scopes: set[str] = set()

        # Add injected scopes and their parents
        for scope in scopes:
            add_scope_tree(needed_scopes, scope)

        # Add scopes with resource providers and their parents
        for scope in ordered:
            if self._resources.get(scope):
                add_scope_tree(needed_scopes, scope)

        return [scope for scope in ordered if scope in needed_scopes]

    # == Provider Registry ==

    def register(
        self,
        dependency_type: Any = NOT_SET,
        factory: Callable[..., Any] = NOT_SET,
        *,
        scope: Scope = "singleton",
        from_context: bool = False,
        override: bool = False,
        alias: Any = NOT_SET,
    ) -> Provider:
        """Register a provider for the specified dependency type."""
        if self.ready and not override:
            raise RuntimeError(
                "Cannot register providers after build() has been called. "
                "All providers must be registered before building the container."
            )

        if factory is NOT_SET:
            factory = dependency_type
        provider = self._register_provider(
            dependency_type, factory, scope, from_context, override, None
        )

        # Register aliases if specified
        for alias_type in to_list(alias):
            self.alias(alias_type, provider.dependency_type)

        return provider

    def alias(self, alias_type: Any, canonical_type: Any, /) -> None:
        """Register an alias for a dependency type."""
        if self.ready:
            raise RuntimeError(
                "Cannot register aliases after build() has been called. "
                "All aliases must be registered before building the container."
            )
        if alias_type == canonical_type:
            raise ValueError("Alias type cannot be the same as canonical type.")
        if alias_type in self._aliases:
            raise ValueError(
                f"Alias `{type_repr(alias_type)}` is already registered "
                f"for `{type_repr(self._aliases[alias_type])}`."
            )
        if canonical_type not in self._providers:
            raise ValueError(
                f"Cannot create alias: provider for `{type_repr(canonical_type)}` "
                "is not registered. Register the provider first."
            )
        self._aliases[alias_type] = canonical_type
        self._aliases_by_canonical[canonical_type].add(alias_type)

    def _resolve_alias(self, dependency_type: Any) -> Any:
        """Resolve an alias to its canonical type."""
        return self._aliases.get(dependency_type, dependency_type)

    def get_aliases_for(self, canonical_type: Any, /) -> set[Any]:
        """Get all aliases that point to the given canonical type."""
        return self._aliases_by_canonical.get(canonical_type, set())

    def is_registered(self, dependency_type: Any, /) -> bool:
        """Check if a provider is registered for the specified dependency type."""
        canonical = self._resolve_alias(dependency_type)
        return canonical in self._providers

    def has_provider_for(self, dependency_type: Any, /) -> bool:
        """Check if a provider exists for the specified dependency type."""
        return self.is_registered(dependency_type) or is_provided(dependency_type)

    def unregister(self, dependency_type: Any, /) -> None:
        """Unregister a provider by dependency type."""
        if not self.is_registered(dependency_type):
            raise LookupError(
                f"The provider `{type_repr(dependency_type)}` is not registered."
            )

        provider = self._get_provider(dependency_type)

        # Cleanup instance context
        if provider.scope != "transient":
            try:
                context = self._get_instance_context(provider.scope)
            except LookupError:
                pass
            else:
                del context[dependency_type]

        # Cleanup provider references
        self._delete_provider(provider)

    def provider(
        self, *, scope: Scope, override: bool = False, alias: Any = NOT_SET
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        """Decorator to register a provider function with the specified scope."""

        def decorator(call: Callable[P, T]) -> Callable[P, T]:
            provider = self._register_provider(
                NOT_SET, call, scope, False, override, None
            )

            # Register aliases if specified
            for alias_type in to_list(alias):
                self.alias(alias_type, provider.dependency_type)

            return call

        return decorator

    def _register_provider(  # noqa: C901
        self,
        dependency_type: Any,
        factory: Callable[..., Any],
        scope: Scope,
        from_context: bool,
        override: bool,
        defaults: dict[str, Any] | None,
    ) -> Provider:
        """Register a provider with the specified scope."""
        # Validate scope is registered
        if scope not in self._scopes:
            raise ValueError(
                f"The scope `{scope}` is not registered. "
                "Please register the scope first using register_scope()."
            )

        # Default factory to dependency_type if not set
        if not from_context and factory is NOT_SET:
            factory = dependency_type

        # Handle from_context providers (context-provided dependencies)
        if from_context:
            if scope in ("singleton", "transient"):
                raise ValueError(
                    f"The `from_context=True` option cannot be used with "
                    f"`{scope}` scope. Use a scoped context like 'request' instead."
                )
            if dependency_type is NOT_SET:
                raise TypeError(
                    "The `dependency_type` parameter is required when using "
                    "`from_context=True`."
                )
            if dependency_type in self._providers and not override:
                raise LookupError(
                    f"The provider `{type_repr(dependency_type)}` is already "
                    "registered."
                )

            provider = Provider(
                dependency_type=dependency_type,
                factory=lambda: None,
                scope=scope,
                from_context=True,
                parameters=(),
                is_class=False,
                is_coroutine=False,
                is_generator=False,
                is_async_generator=False,
                is_async=False,
                is_resource=False,
            )
        else:
            # Regular provider registration
            name = type_repr(factory)
            kind = ProviderKind.from_call(factory)
            is_class = kind == ProviderKind.CLASS
            is_coroutine = kind == ProviderKind.COROUTINE
            is_generator = kind == ProviderKind.GENERATOR
            is_async_generator = kind == ProviderKind.ASYNC_GENERATOR
            is_resource = is_generator or is_async_generator

            if scope == "transient" and is_resource:
                raise TypeError(
                    f"The resource provider `{name}` is attempting to register "
                    "with a transient scope, which is not allowed."
                )

            signature = inspect.signature(factory, eval_str=True)

            # Detect dependency_type from factory or return annotation
            if dependency_type is NOT_SET:
                dependency_type = factory if is_class else signature.return_annotation
                if dependency_type is inspect.Signature.empty:
                    dependency_type = None

            # Unwrap iterator types for resources
            type_origin = get_origin(dependency_type)
            if is_iterator_type(dependency_type) or is_iterator_type(type_origin):
                args = get_args(dependency_type)
                if not args:
                    raise TypeError(
                        f"Cannot use `{name}` resource type annotation "
                        "without actual type argument."
                    )
                dependency_type = args[0]
                if is_none_type(dependency_type):
                    dependency_type = type(f"Event_{uuid.uuid4().hex}", (Event,), {})

            if is_none_type(dependency_type):
                raise TypeError(f"Missing `{name}` provider return annotation.")

            if dependency_type in self._providers and not override:
                raise LookupError(
                    f"The provider `{type_repr(dependency_type)}` is already "
                    "registered."
                )

            # Process parameters (lazy - store without resolving dependencies)
            parameters: list[ProviderParameter] = []

            # Build TypeVar map for generic class inheritance
            typevar_map = (
                build_typevar_map(cast(type[Any], factory)) if is_class else {}
            )

            for param in signature.parameters.values():
                if param.annotation is inspect.Parameter.empty:
                    raise TypeError(
                        f"Missing provider `{name}` "
                        f"dependency `{param.name}` annotation."
                    )
                if param.kind == inspect.Parameter.POSITIONAL_ONLY:
                    raise TypeError(
                        f"Positional-only parameters "
                        f"are not allowed in the provider `{name}`."
                    )

                has_default = param.default is not inspect.Parameter.empty
                # Markers are injection markers, not real defaults
                if has_default and isinstance(param.default, Marker):
                    has_default = False
                default = param.default if has_default else NOT_SET

                # Skip parameters provided via defaults (for create() method)
                if defaults and param.name in defaults:
                    continue

                # Lazy registration: Store parameter without resolving dependencies
                parameters.append(
                    ProviderParameter(
                        dependency_type=resolve_typevars(param.annotation, typevar_map),
                        name=param.name,
                        default=default,
                        has_default=has_default,
                        provider=None,  # Lazy - will be resolved in build()
                        shared_scope=False,  # Lazy - will be computed in build()
                    )
                )

            provider = Provider(
                dependency_type=dependency_type,
                factory=factory,
                scope=scope,
                from_context=False,
                parameters=tuple(parameters),
                is_class=is_class,
                is_coroutine=is_coroutine,
                is_generator=is_generator,
                is_async_generator=is_async_generator,
                is_async=is_coroutine or is_async_generator,
                is_resource=is_resource,
            )

        self._set_provider(provider)
        if override:
            self._resolver.clear_caches()

        # Resolve dependencies for providers registered after build()
        if self.ready:
            provider = self._ensure_provider_resolved(provider, set())

        return provider

    def _get_provider(self, dependency_type: Any) -> Provider:
        """Get provider by dependency type, resolving aliases."""
        canonical = self._resolve_alias(dependency_type)
        try:
            return self._providers[canonical]
        except KeyError:
            raise LookupError(
                f"The provider for `{type_repr(dependency_type)}` has "
                "not been registered. Please ensure that the provider is "
                "properly registered before attempting to use it."
            ) from None

    def _get_or_register_provider(
        self, dependency_type: Any, defaults: dict[str, Any] | None = None
    ) -> Provider:
        """Get or register a provider by dependency type."""
        registered = False
        try:
            provider = self._get_provider(dependency_type)
        except LookupError:
            if inspect.isclass(dependency_type) and is_provided(dependency_type):
                provider = self._register_provider(
                    dependency_type,
                    dependency_type,
                    dependency_type.__provided__.get("scope", "singleton"),
                    dependency_type.__provided__.get("from_context", False),
                    False,
                    defaults,
                )
                # Register aliases if specified
                if not self.ready:
                    aliases = to_list(dependency_type.__provided__.get("alias"))
                    for alias_type in aliases:
                        self.alias(alias_type, dependency_type)
                registered = True
            else:
                raise LookupError(
                    f"The provider `{type_repr(dependency_type)}` is either not "
                    "registered, not provided, or not set in the scoped context. "
                    "Please ensure that the provider is properly registered and "
                    "that the class is decorated with a scope before attempting to "
                    "use it."
                ) from None

        # Resolve dependencies:
        # - For existing providers: only if container is not built yet
        # - For newly auto-registered providers: always (even after build)
        if registered or not self.ready:
            provider = self._ensure_provider_resolved(provider, set())

        return provider

    def _ensure_provider_resolved(  # noqa: C901
        self, provider: Provider, resolving: set[Any]
    ) -> Provider:
        """Ensure dependencies are resolved, resolving on-the-fly if needed."""
        # Check if we're already resolving this provider (circular dependency)
        if provider.dependency_type in resolving:
            return provider

        # Check if already resolved by examining parameters
        # A provider is resolved if all its parameters either:
        # 1. Have a provider set (provider is not None), OR
        # 2. Have a default value, OR
        # 3. Are marked for context.set() (provider=None but in unresolved list)
        all_resolved = all(
            param.provider is not None
            or param.has_default
            or (
                param.provider is None and param.shared_scope
            )  # Unresolved for context.set()
            for param in provider.parameters
        )
        if all_resolved:
            return provider

        # Mark as currently being resolved
        resolving = resolving | {provider.dependency_type}

        # Resolve dependencies for this provider
        resolved_params: list[ProviderParameter] = []

        for param in provider.parameters:
            if param.provider is not None:
                # Already resolved
                resolved_params.append(param)
                continue

            dependency_type = param.dependency_type

            # Try to resolve the dependency
            # First check if this would create a circular dependency
            if dependency_type in resolving:
                raise ValueError(
                    f"Circular dependency detected: {provider} depends on "
                    f"{type_repr(dependency_type)}"
                )

            try:
                dep_provider = self._get_provider(dependency_type)
            except LookupError:
                # Check if it's a @provided class
                if inspect.isclass(dependency_type) and is_provided(dependency_type):
                    provided_scope = dependency_type.__provided__["scope"]
                    from_context = dependency_type.__provided__.get(
                        "from_context", False
                    )

                    # Auto-register @provided class
                    dep_provider = self._register_provider(
                        dependency_type,
                        dependency_type,
                        provided_scope,
                        from_context,
                        False,
                        None,
                    )
                    # Register aliases if specified
                    aliases = to_list(dependency_type.__provided__.get("alias"))
                    for alias_type in aliases:
                        self.alias(alias_type, dependency_type)
                    # Recursively ensure the @provided class is resolved
                    dep_provider = self._ensure_provider_resolved(
                        dep_provider, resolving
                    )
                elif param.has_default:
                    # Has default, can be missing
                    resolved_params.append(param)
                    continue
                else:
                    # Required dependency is missing
                    raise LookupError(
                        f"The provider `{provider}` depends on `{param.name}` of type "
                        f"`{type_repr(dependency_type)}`, which has not been "
                        f"registered or set. To resolve this, ensure that "
                        f"`{param.name}` is registered before resolving, "
                        f"or register it with `from_context=True` if it should be "
                        f"provided via scoped context."
                    ) from None

            # If the dependency is a from_context provider, mark it appropriately
            if dep_provider.from_context:
                # shared_scope should only be True when scopes match,
                # so that cross-scope from_context deps fall back to their
                # own scope's ContextVar instead of receiving the wrong context.
                shared_scope = (
                    dep_provider.scope == provider.scope
                    and provider.scope != "transient"
                )
                resolved_params.append(
                    ProviderParameter(
                        name=param.name,
                        dependency_type=dependency_type,
                        default=param.default,
                        has_default=param.has_default,
                        provider=dep_provider,
                        shared_scope=shared_scope,
                    )
                )
                continue

            # Ensure dependency is also resolved
            dep_provider = self._ensure_provider_resolved(dep_provider, resolving)

            # Validate scope compatibility
            scope_hierarchy = (
                self._scopes.get(provider.scope, ())
                if provider.scope != "transient"
                else ()
            )
            if scope_hierarchy and dep_provider.scope not in scope_hierarchy:
                raise ValueError(
                    f"The provider `{provider}` with a `{provider.scope}` scope "
                    f"cannot depend on `{dep_provider}` with a "
                    f"`{dep_provider.scope}` scope. Please ensure all providers are "
                    f"registered with matching scopes."
                )

            # Calculate shared_scope
            shared_scope = (
                dep_provider.scope == provider.scope and provider.scope != "transient"
            )

            # Create resolved parameter (use unwrapped annotation)
            resolved_params.append(
                ProviderParameter(
                    name=param.name,
                    dependency_type=dependency_type,
                    default=param.default,
                    has_default=param.has_default,
                    provider=dep_provider,
                    shared_scope=shared_scope,
                )
            )

        # Replace provider with resolved version
        resolved_provider = Provider(
            factory=provider.factory,
            scope=provider.scope,
            dependency_type=provider.dependency_type,
            parameters=tuple(resolved_params),
            is_class=provider.is_class,
            is_coroutine=provider.is_coroutine,
            is_generator=provider.is_generator,
            is_async_generator=provider.is_async_generator,
            is_async=provider.is_async,
            is_resource=provider.is_resource,
            from_context=provider.from_context,
        )
        self._providers[provider.dependency_type] = resolved_provider

        return resolved_provider

    def _set_provider(self, provider: Provider) -> None:
        """Set a provider by dependency type."""
        self._providers[provider.dependency_type] = provider
        if provider.is_resource:
            self._resources[provider.scope].append(provider.dependency_type)

    def _delete_provider(self, provider: Provider) -> None:
        """Delete a provider."""
        if provider.dependency_type in self._providers:
            del self._providers[provider.dependency_type]
        if provider.is_resource:
            self._resources[provider.scope].remove(provider.dependency_type)
        # Remove aliases pointing to this provider
        for alias in self._aliases_by_canonical.pop(provider.dependency_type, set()):
            self._aliases.pop(alias, None)

    # == Instance Resolution ==

    @overload
    def resolve(self, dependency_type: type[T], /) -> T: ...

    @overload
    def resolve(self, dependency_type: T, /) -> T: ...  # type: ignore

    def resolve(self, dependency_type: type[T], /) -> T:
        """Resolve an instance by dependency type using compiled sync resolver."""
        cached = self._resolver.get_cached(dependency_type, is_async=False)
        if cached is not None:
            return cached.resolve(self)

        provider = self._get_or_register_provider(dependency_type)
        compiled = self._resolver.compile(provider, is_async=False)
        return compiled.resolve(self)

    @overload
    async def aresolve(self, dependency_type: type[T], /) -> T: ...

    @overload
    async def aresolve(self, dependency_type: T, /) -> T: ...

    async def aresolve(self, dependency_type: type[T], /) -> T:
        """Resolve an instance by dependency type asynchronously."""
        cached = self._resolver.get_cached(dependency_type, is_async=True)
        if cached is not None:
            return await cached.resolve(self)

        provider = self._get_or_register_provider(dependency_type)
        compiled = self._resolver.compile(provider, is_async=True)
        return await compiled.resolve(self)

    def create(self, dependency_type: type[T], /, **defaults: Any) -> T:
        """Create an instance by dependency type."""
        if not defaults:
            cached = self._resolver.get_cached(dependency_type, is_async=False)
            if cached is not None:
                return cached.create(self, None)

        provider = self._get_or_register_provider(dependency_type, defaults)
        compiled = self._resolver.compile(provider, is_async=False)
        return compiled.create(self, defaults or None)

    async def acreate(self, dependency_type: type[T], /, **defaults: Any) -> T:
        """Create an instance by dependency type asynchronously."""
        if not defaults:
            cached = self._resolver.get_cached(dependency_type, is_async=True)
            if cached is not None:
                return await cached.create(self, None)

        provider = self._get_or_register_provider(dependency_type, defaults)
        compiled = self._resolver.compile(provider, is_async=True)
        return await compiled.create(self, defaults or None)

    def is_resolved(self, dependency_type: Any, /) -> bool:
        """Check if an instance for the dependency type exists."""
        try:
            provider = self._get_provider(dependency_type)
        except LookupError:
            return False
        if provider.scope == "transient":
            return False
        context = self._get_instance_context(provider.scope)
        return dependency_type in context

    def release(self, dependency_type: Any, /) -> None:
        """Release an instance by dependency type."""
        provider = self._get_provider(dependency_type)
        if provider.scope == "transient":
            return None
        context = self._get_instance_context(provider.scope)
        del context[dependency_type]

    def reset(self) -> None:
        """Reset resolved instances."""
        for dependency_type, provider in self._providers.items():
            if provider.scope == "transient":
                continue
            try:
                context = self._get_instance_context(provider.scope)
            except LookupError:
                continue
            del context[dependency_type]

    # == Injection Utilities ==

    @overload
    def inject(self, func: Callable[P, T]) -> Callable[P, T]: ...

    @overload
    def inject(self) -> Callable[[Callable[P, T]], Callable[P, T]]: ...

    def inject(
        self, func: Callable[P, T] | None = None
    ) -> Callable[[Callable[P, T]], Callable[P, T]] | Callable[P, T]:
        """Decorator to inject dependencies into a callable."""

        def decorator(call: Callable[P, T]) -> Callable[P, T]:
            return self._injector.inject(call)

        if func is None:
            return decorator
        return decorator(func)

    def run(self, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        """Run the given function with injected dependencies."""
        return self._injector.inject(func)(*args, **kwargs)

    def validate_injected_parameter(
        self, parameter: inspect.Parameter, *, call: Callable[..., Any]
    ) -> tuple[Any, bool, Marker | None]:
        """Validate an injected parameter."""
        return self._injector.validate_parameter(parameter, call=call)

    # == Module Registration ==

    def register_module(self, module: ModuleDef) -> None:
        """Register a module as a callable, module type, or module instance."""
        self._modules.register(module)

    # == Package Scanning ==

    def scan(
        self,
        /,
        packages: PackageOrIterable,
        *,
        tags: Iterable[str] | None = None,
        ignore: PackageOrIterable | None = None,
    ) -> None:
        self._scanner.scan(packages=packages, tags=tags, ignore=ignore)

    # == Build ==

    def build(self) -> None:
        """Build the container by validating the complete dependency graph."""
        if self.ready:
            raise RuntimeError("Container has already been built")

        self._resolve_provider_dependencies()
        self._detect_circular_dependencies()
        self._validate_scope_compatibility()

        self._ready = True

    def rebuild(self) -> None:
        """Rebuild the container by re-validating the complete dependency graph."""
        if self._ready:
            self._ready = False
            self._resolver.clear_caches()
        self.build()

    def graph(
        self,
        output_format: Literal["tree", "mermaid", "dot", "json"] = "tree",
        *,
        full_path: bool = False,
        **kwargs: Any,
    ) -> str:
        """Draw the dependency graph."""
        if not self.ready:
            self.build()
        return self._graph.draw(
            output_format=output_format,
            full_path=full_path,
            **kwargs,
        )

    def _resolve_provider_dependencies(self) -> None:
        """Resolve all provider dependencies by filling in provider references."""
        for dependency_type, provider in list(self._providers.items()):
            resolved_params: list[ProviderParameter] = []

            for param in provider.parameters:
                if param.provider is not None:
                    # Already resolved
                    resolved_params.append(param)
                    continue

                param_dependency_type = param.dependency_type

                # Try to resolve the dependency
                try:
                    dep_provider = self._get_provider(param_dependency_type)
                except LookupError:
                    # Check if it's a @provided class
                    if inspect.isclass(param_dependency_type) and is_provided(
                        param_dependency_type
                    ):
                        provided_scope = param_dependency_type.__provided__["scope"]

                        # Auto-register @provided class
                        dep_provider = self._register_provider(
                            param_dependency_type,
                            param_dependency_type,
                            provided_scope,
                            False,
                            False,
                            None,
                        )
                        # Register aliases if specified
                        provided_meta = param_dependency_type.__provided__
                        for alias_type in to_list(provided_meta.get("alias")):
                            self.alias(alias_type, param_dependency_type)
                    elif param.has_default:
                        # Has default, can be missing
                        resolved_params.append(param)
                        continue
                    else:
                        # Required dependency is missing
                        raise LookupError(
                            f"The provider `{provider}` depends on "
                            f"`{param.name}` of type "
                            f"`{type_repr(param_dependency_type)}`, which has not been "
                            f"registered or set. To resolve this, ensure that "
                            f"`{param.name}` is registered before calling build(), "
                            f"or register it with `from_context=True` if it should be "
                            f"provided via scoped context."
                        ) from None

                # Calculate shared_scope
                shared_scope = (
                    dep_provider.scope == provider.scope
                    and provider.scope != "transient"
                )

                # If the dependency is a from_context provider, mark it appropriately
                if dep_provider.from_context:
                    resolved_params.append(
                        ProviderParameter(
                            name=param.name,
                            dependency_type=param_dependency_type,
                            default=param.default,
                            has_default=param.has_default,
                            provider=dep_provider,
                            shared_scope=shared_scope,
                        )
                    )
                    continue

                # Create resolved parameter
                resolved_params.append(
                    ProviderParameter(
                        name=param.name,
                        dependency_type=param_dependency_type,
                        default=param.default,
                        has_default=param.has_default,
                        provider=dep_provider,
                        shared_scope=shared_scope,
                    )
                )

            # Replace provider with resolved version
            resolved_provider = Provider(
                factory=provider.factory,
                scope=provider.scope,
                dependency_type=provider.dependency_type,
                parameters=tuple(resolved_params),
                is_class=provider.is_class,
                is_coroutine=provider.is_coroutine,
                is_generator=provider.is_generator,
                is_async_generator=provider.is_async_generator,
                is_async=provider.is_async,
                is_resource=provider.is_resource,
                from_context=provider.from_context,
            )
            self._providers[dependency_type] = resolved_provider

    def _detect_circular_dependencies(self) -> None:
        """Detect circular dependencies in the provider graph."""

        def visit(
            dependency_type: Any,
            provider: Provider,
            path: list[str],
            visited: set[Any],
            in_path: set[Any],
        ) -> None:
            """DFS traversal to detect cycles."""
            if dependency_type in in_path:
                # Found a cycle!
                cycle_start = next(
                    i for i, name in enumerate(path) if name == str(provider)
                )
                cycle_path = " -> ".join([*path[cycle_start:], str(provider)])
                raise ValueError(
                    f"Circular dependency detected: {cycle_path}. "
                    f"Please restructure your dependencies to break the cycle."
                )

            if dependency_type in visited:
                return

            visited.add(dependency_type)
            in_path.add(dependency_type)
            path.append(str(provider))

            # Visit dependencies
            for param in provider.parameters:
                # Look up the dependency provider from self._providers instead of
                # using param.provider, which might be stale/unresolved
                if param.dependency_type in self._providers:
                    dep_provider = self._providers[param.dependency_type]
                    visit(
                        param.dependency_type,
                        dep_provider,
                        path,
                        visited,
                        in_path,
                    )

            path.pop()
            in_path.remove(dependency_type)

        visited: set[Any] = set()

        for dependency_type, provider in self._providers.items():
            if dependency_type not in visited:
                visit(dependency_type, provider, [], visited, set())

    def _validate_scope_compatibility(self) -> None:
        """Validate that all dependencies have compatible scopes."""
        for provider in self._providers.values():
            scope = provider.scope

            # Skip validation for transient (can depend on anything)
            if scope == "transient":
                continue

            # Get scope hierarchy for this provider
            scope_hierarchy = (
                self._scopes.get(scope, ()) if scope != "transient" else ()
            )

            # Check each dependency
            for param in provider.parameters:
                if param.provider is None:
                    # Unresolved (allowed for scoped providers)
                    continue

                dep_scope = param.provider.scope

                # Validate scope compatibility
                if scope_hierarchy and dep_scope not in scope_hierarchy:
                    raise ValueError(
                        f"The provider `{provider}` with a `{scope}` scope "
                        f"cannot depend on `{param.provider}` with a "
                        f"`{dep_scope}` scope. Please ensure all providers are "
                        f"registered with matching scopes."
                    )

    # == Testing / Override Support ==

    def enable_test_mode(self) -> None:
        """Enable test mode for override support on all resolutions."""
        self._test_mode = True

    def disable_test_mode(self) -> None:
        """Disable test mode for override support on all resolutions."""
        self._test_mode = False

    @contextlib.contextmanager
    def test_mode(self) -> Iterator[None]:
        if self._test_mode:
            yield
            return

        self._test_mode = True
        try:
            yield
        finally:
            self._test_mode = False

    @contextlib.contextmanager
    def override(
        self,
        dependency_type: Any,
        /,
        instance: Any,
    ) -> Iterator[None]:
        """Override a dependency with a specific instance for testing."""
        if not self._test_mode:
            warnings.warn(
                "Using override() without enabling test mode. "
                "Consider using `with container.test_mode():` for consistent behavior.",
                UserWarning,
                stacklevel=2,
            )

        if dependency_type is NOT_SET:
            raise TypeError("override() missing required argument: 'dependency_type'")

        if instance is NOT_SET:
            raise TypeError("override() missing required argument: 'instance'")

        if not self.has_provider_for(dependency_type):
            raise LookupError(
                f"The provider `{type_repr(dependency_type)}` is not registered."
            )
        self._resolver.add_override(dependency_type, instance)
        try:
            yield
        finally:
            self._resolver.remove_override(dependency_type)


def import_container(container_path: str) -> Container:
    """Import container from a string path."""
    # Replace colon with dot for unified processing
    container_path = container_path.replace(":", ".")

    try:
        module_path, attr_name = container_path.rsplit(".", 1)
    except ValueError as exc:
        raise ImportError(
            f"Invalid container path '{container_path}'. "
            "Expected format: 'module.path:attribute' or 'module.path.attribute'"
        ) from exc

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Failed to import module '{module_path}' "
            f"from container path '{container_path}'"
        ) from exc

    try:
        container_or_factory = getattr(module, attr_name)
    except AttributeError as exc:
        raise ImportError(
            f"Module '{module_path}' has no attribute '{attr_name}'"
        ) from exc

    # If it's a callable (factory), call it
    if callable(container_or_factory) and not isinstance(
        container_or_factory, Container
    ):
        container = container_or_factory()
    else:
        container = container_or_factory

    if not isinstance(container, Container):
        raise ImportError(
            f"Expected Container instance, got {type(container).__name__} "
            f"from '{container_path}'"
        )

    return container
