from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Any

from ._decorators import Provided, is_injectable, is_provided
from ._types import to_list

if TYPE_CHECKING:
    from ._container import Container

Package = ModuleType | str
PackageOrIterable = Package | Iterable[Package]


@dataclass(kw_only=True)
class ScannedDependency:
    member: Any
    module: ModuleType

    def __post_init__(self) -> None:
        # Unwrap decorated functions if necessary
        if hasattr(self.member, "__wrapped__"):
            self.member = self.member.__wrapped__


class Scanner:
    def __init__(self, container: Container) -> None:
        self._container = container
        self._importing_modules: set[str] = set()
        self._scanning = False

    def scan(
        self,
        /,
        packages: PackageOrIterable,
        *,
        tags: Iterable[str] | None = None,
        ignore: PackageOrIterable | None = None,
    ) -> None:
        """Scan packages or modules for decorated members and inject dependencies."""
        if self._scanning:
            raise RuntimeError(
                "Circular import detected: scan() called recursively!\n\n"
                "This happens when a scanned module triggers container creation "
                "(e.g., via lazy proxy).\n\n"
                "Solutions:\n"
                "- Add the problematic module to scan() ignore list\n"
                "- Move container imports inside functions (lazy import)\n"
                "- Avoid lazy container initialization in scanned modules"
            )

        self._scanning = True
        try:
            self._do_scan(packages, tags=tags, ignore=ignore)
        finally:
            self._scanning = False

    def _do_scan(
        self,
        packages: PackageOrIterable,
        *,
        tags: Iterable[str] | None = None,
        ignore: PackageOrIterable | None = None,
    ) -> None:
        """Internal scan implementation."""
        if isinstance(packages, (ModuleType, str)):
            packages = [packages]

        tags_list = list(tags) if tags else []
        ignore_prefixes = self._normalize_ignore(ignore)
        provided_classes: list[type[Provided]] = []
        injectable_dependencies: list[ScannedDependency] = []

        # Single pass: collect both @provided classes and @injectable functions
        for module in self._iter_modules(packages, ignore_prefixes=ignore_prefixes):
            provided_classes.extend(self._scan_module_for_provided(module))
            injectable_dependencies.extend(
                self._scan_module_for_injectable(module, tags=tags_list)
            )

        # First: register @provided classes
        for cls in provided_classes:
            if not self._container.is_registered(cls):
                scope = cls.__provided__["scope"]
                from_context = cls.__provided__.get("from_context", False)
                self._container.register(
                    cls, cls, scope=scope, from_context=from_context
                )
            # Create aliases if specified (alias → cls)
            for alias_type in to_list(cls.__provided__.get("alias")):
                self._container.alias(alias_type, cls)

        # Second: inject @injectable functions
        for dependency in injectable_dependencies:
            decorated = self._container.inject()(dependency.member)
            setattr(dependency.module, dependency.member.__name__, decorated)

    def _normalize_ignore(self, ignore: PackageOrIterable | None) -> list[str]:
        """Normalize ignore parameter to a list of module name prefixes."""
        if ignore is None:
            return []

        if isinstance(ignore, (ModuleType, str)):
            ignore = [ignore]

        prefixes: list[str] = []
        for item in ignore:
            if isinstance(item, ModuleType):
                prefixes.append(item.__name__)
            else:
                prefixes.append(item)
        return prefixes

    def _should_ignore_module(
        self, module_name: str, ignore_prefixes: list[str]
    ) -> bool:
        """Check if a module should be ignored based on ignore prefixes."""
        for prefix in ignore_prefixes:
            if module_name == prefix or module_name.startswith(prefix + "."):
                return True
        return False

    def _iter_modules(
        self, packages: Iterable[Package], *, ignore_prefixes: list[str]
    ) -> Iterator[ModuleType]:
        """Iterate over all modules in the given packages."""
        for package in packages:
            if isinstance(package, str):
                package = importlib.import_module(package)

            # Single module (not a package)
            if not hasattr(package, "__path__"):
                if not self._should_ignore_module(package.__name__, ignore_prefixes):
                    yield package
                continue

            # Package - walk all submodules
            for module_info in pkgutil.walk_packages(
                package.__path__, prefix=package.__name__ + "."
            ):
                if not self._should_ignore_module(module_info.name, ignore_prefixes):
                    yield from self._import_module_with_tracking(module_info.name)

    def _import_module_with_tracking(self, module_name: str) -> Iterator[ModuleType]:
        """Import a module while tracking for circular imports."""
        # Check if we're already importing this module (circular import)
        if module_name in self._importing_modules:
            import_chain = " -> ".join(sorted(self._importing_modules))
            raise RuntimeError(
                f"Circular import detected during container scanning!\n"
                f"Module '{module_name}' is being imported while already "
                f"in the import chain.\n"
                f"Import chain: {import_chain} -> {module_name}\n\n"
                f"This usually happens when:\n"
                f"1. A scanned module imports the container at module level\n"
                f"2. The container creation triggers scanning\n"
                f"3. Scanning tries to import the module again\n\n"
                f"Solutions:\n"
                f"- Add '{module_name}' to the ignore list\n"
                f"- Move container imports inside functions (lazy import)\n"
                f"- Check for modules importing the container module"
            )

        # Track that we're importing this module
        self._importing_modules.add(module_name)
        try:
            module = importlib.import_module(module_name)
            yield module
        finally:
            # Always cleanup, even if import fails
            self._importing_modules.discard(module_name)

    def _scan_module_for_provided(self, module: ModuleType) -> list[type[Provided]]:
        """Scan a module for @provided classes."""
        provided_classes: list[type[Provided]] = []

        for _, member in inspect.getmembers(module, predicate=inspect.isclass):
            if getattr(member, "__module__", None) != module.__name__:
                continue

            if is_provided(member):
                provided_classes.append(member)

        return provided_classes

    def _scan_module_for_injectable(
        self, module: ModuleType, *, tags: list[str]
    ) -> list[ScannedDependency]:
        """Scan a module for @injectable functions."""
        dependencies: list[ScannedDependency] = []

        for _, member in inspect.getmembers(module, predicate=callable):
            if getattr(member, "__module__", None) != module.__name__:
                continue

            if self._should_include_member(member, tags=tags):
                dependencies.append(ScannedDependency(member=member, module=module))

        return dependencies

    @staticmethod
    def _should_include_member(member: Callable[..., Any], *, tags: list[str]) -> bool:
        """Determine if a member should be included based on tags or marker defaults."""
        if is_injectable(member):
            member_tags = set(member.__injectable__["tags"] or [])
            if tags:
                return bool(set(tags) & member_tags)
            return True  # No tags passed → include all injectables

        return False
