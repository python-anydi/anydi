"""AnyDI Typer extension."""

from __future__ import annotations

import concurrent.futures
import contextlib
import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import sniffio
from typer import Typer

from anydi import Container, Scope
from anydi._decorators import is_provided

__all__ = ["install"]


def _wrap_async_callback_no_injection(callback: Callable[..., Any]) -> Any:
    """Wrap async callback without injection in anyio.run()."""

    @functools.wraps(callback)
    def async_no_injection_wrapper(*args: Any, **kwargs: Any) -> Any:
        # Check if we're already in an async context
        try:
            sniffio.current_async_library()
            # We're in an async context, run anyio.run() in a separate thread
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(anyio.run, callback, *args, **kwargs)
                return future.result()
        except sniffio.AsyncLibraryNotFoundError:
            # Not in an async context, can use anyio.run directly
            return anyio.run(callback, *args, **kwargs)

    return async_no_injection_wrapper


def _wrap_async_callback_with_injection(
    callback: Callable[..., Awaitable[Any]],
    container: Container,
    sig: inspect.Signature,
    non_injected_params: list[inspect.Parameter],
    scopes: set[Scope],
) -> Any:
    """Wrap async callback with injection in anyio.run()."""

    @functools.wraps(callback)
    def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        async def _run() -> Any:
            # Get scopes for execution (injected OR have resources)
            needed_scopes = container.get_context_scopes(scopes)

            async with contextlib.AsyncExitStack() as stack:
                # Start scoped contexts in dependency order
                for scope in needed_scopes:
                    if scope == "singleton":
                        await stack.enter_async_context(container)
                    else:
                        await stack.enter_async_context(
                            container.ascoped_context(scope)
                        )

                return await container.run(callback, *args, **kwargs)

        # Check if we're already in an async context
        try:
            sniffio.current_async_library()
            # We're in an async context, run anyio.run() in a separate thread
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(anyio.run, _run)
                return future.result()
        except sniffio.AsyncLibraryNotFoundError:
            # Not in an async context, can use anyio.run directly
            return anyio.run(_run)

    # Update the wrapper's signature to only show non-injected parameters to Typer
    async_wrapper.__signature__ = sig.replace(parameters=non_injected_params)  # type: ignore

    return async_wrapper


def _process_callback(callback: Callable[..., Any], container: Container) -> Any:  # noqa: C901
    """Validate and wrap a callback for dependency injection."""
    sig = inspect.signature(callback, eval_str=True)
    injected_param_names: set[str] = set()
    non_injected_params: list[inspect.Parameter] = []
    scopes: set[Scope] = set()

    # Validate parameters and collect which ones need injection
    for parameter in sig.parameters.values():
        dependency_type, should_inject, _ = container.validate_injected_parameter(
            parameter, call=callback
        )
        processed_parameter = container._injector.unwrap_parameter(parameter)
        if should_inject:
            injected_param_names.add(parameter.name)
            # Resolve alias to canonical type if needed
            canonical_type = container.aliases.get(dependency_type, dependency_type)
            try:
                scopes.add(container.providers[canonical_type].scope)
            except KeyError:
                if inspect.isclass(dependency_type) and is_provided(dependency_type):
                    scopes.add(dependency_type.__provided__["scope"])
        else:
            non_injected_params.append(processed_parameter)

    # If no parameters need injection and callback is not async, return original
    if not injected_param_names and not inspect.iscoroutinefunction(callback):
        return callback

    # If async callback with no injection, just wrap in anyio.run()
    if not injected_param_names and inspect.iscoroutinefunction(callback):
        return _wrap_async_callback_no_injection(callback)

    # Handle async callbacks - wrap them in anyio.run() for Typer
    if inspect.iscoroutinefunction(callback):
        return _wrap_async_callback_with_injection(
            callback, container, sig, non_injected_params, scopes
        )

    @functools.wraps(callback)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Get scopes for execution (injected OR have resources)
        needed_scopes = container.get_context_scopes(scopes)

        with contextlib.ExitStack() as stack:
            # Start scoped contexts in dependency order
            for scope in needed_scopes:
                if scope == "singleton":
                    stack.enter_context(container)
                else:
                    stack.enter_context(container.scoped_context(scope))

            return container.run(callback, *args, **kwargs)

    # Update the wrapper's signature to only show non-injected parameters to Typer
    wrapper.__signature__ = sig.replace(parameters=non_injected_params)  # type: ignore

    return wrapper


def install(app: Typer, container: Container) -> None:
    """Install AnyDI into a Typer application."""
    # Process main callback if exists
    if app.registered_callback:
        callback = app.registered_callback.callback
        if callback:
            app.registered_callback.callback = _process_callback(callback, container)

    # Process all registered commands
    for command_info in app.registered_commands:
        callback = command_info.callback
        if callback:
            command_info.callback = _process_callback(callback, container)

    # Process nested Typer groups
    for group_info in app.registered_groups:
        # Recursively install for nested Typer apps
        if group_info.typer_instance:
            install(group_info.typer_instance, container)
