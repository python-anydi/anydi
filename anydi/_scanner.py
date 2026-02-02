from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Iterable, Iterator
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
    _scanning_packages: set[str] = set()

    def __init__(self, container: Container) -> None:
        self._container = container
        self._importing_modules: set[str] = set()

    def scan(
        self,
        /,
        packages: PackageOrIterable,
        *,
        tags: Iterable[str] | None = None,
        ignore: PackageOrIterable | None = None,
    ) -> None:
        """Scan packages or modules for decorated members and inject dependencies.

        Supports relative package paths (like Python's relative imports):
        - "." scans the caller's package
        - ".submodule" scans a submodule of the caller's package
        - ".." scans the parent package
        - "..sibling" scans a sibling package
        """
        if isinstance(packages, (ModuleType, str)):
            packages = [packages]

        # Resolve relative package paths
        caller_package = self._get_caller_package(packages, ignore)
        packages = self._resolve_relative_packages(packages, caller_package)
        ignore = self._resolve_relative_packages(ignore, caller_package)

        pkg_names = {p if isinstance(p, str) else p.__name__ for p in packages}
        overlap = pkg_names & Scanner._scanning_packages
        if overlap:
            raise RuntimeError(
                f"Circular import detected: scan() called recursively!\n\n"
                f"Already scanning packages: {', '.join(sorted(overlap))}\n\n"
                "This happens when a scanned module triggers container creation "
                "(e.g., via lazy proxy).\n\n"
                "Solutions:\n"
                "- Add the problematic module to scan() ignore list\n"
                "- Move container imports inside functions (lazy import)\n"
                "- Avoid lazy container initialization in scanned modules"
            )

        Scanner._scanning_packages.update(pkg_names)
        try:
            self._do_scan(packages, tags=tags, ignore=ignore)
        finally:
            Scanner._scanning_packages -= pkg_names

    def _do_scan(  # noqa: C901
        self,
        packages: PackageOrIterable,
        *,
        tags: Iterable[str] | None = None,
        ignore: PackageOrIterable | None = None,
    ) -> None:
        """Internal scan implementation."""
        if isinstance(packages, (ModuleType, str)):
            packages = [packages]

        tags_set: set[str] = set(tags) if tags else set()
        ignore_prefixes = self._normalize_ignore(ignore)
        provided_classes: list[type[Provided]] = []
        injectable_dependencies: list[ScannedDependency] = []

        # Single pass: collect both @provided classes and @injectable functions
        for module in self._iter_modules(packages, ignore_prefixes=ignore_prefixes):
            module_name = module.__name__
            for name, member in vars(module).items():
                if name.startswith("_"):
                    continue
                if getattr(member, "__module__", None) != module_name:
                    continue

                if inspect.isclass(member) and is_provided(member):
                    provided_classes.append(member)
                elif callable(member) and is_injectable(member):
                    member_tags = set(member.__injectable__["tags"] or ())
                    if not tags_set or (tags_set & member_tags):
                        injectable_dependencies.append(
                            ScannedDependency(member=member, module=module)
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

    def _has_relative_packages(self, *package_lists: PackageOrIterable | None) -> bool:
        """Check if any package list contains relative paths."""
        for packages in package_lists:
            if packages is None:
                continue
            if isinstance(packages, str):
                if packages.startswith("."):
                    return True
            elif isinstance(packages, ModuleType):
                continue
            else:
                for p in packages:
                    if isinstance(p, str) and p.startswith("."):
                        return True
        return False

    def _get_caller_package(
        self,
        packages: Iterable[Package],
        ignore: PackageOrIterable | None,
    ) -> str | None:
        """Get the package name of the module that called scan()."""
        if not self._has_relative_packages(packages, ignore):
            return None

        frame = inspect.currentframe()
        try:
            while frame is not None:
                frame = frame.f_back
                if frame is None:
                    break
                module_name = frame.f_globals.get("__name__")
                if module_name and not module_name.startswith("anydi"):
                    # Return package portion (remove module name if present)
                    if "." in module_name:
                        return module_name.rsplit(".", 1)[0]
                    return module_name
        finally:
            del frame

        raise ValueError(
            "Cannot use relative package paths: unable to determine caller package. "
            "Use absolute package names instead."
        )

    def _resolve_relative_name(self, relative_name: str, base_package: str) -> str:
        """Resolve a relative package name to absolute."""
        num_dots = len(relative_name) - len(relative_name.lstrip("."))
        remainder = relative_name[num_dots:]

        package_parts = base_package.split(".")

        # Navigate up for parent references (..)
        if num_dots > 1:
            levels_up = num_dots - 1
            if levels_up >= len(package_parts):
                raise ValueError(
                    f"Cannot resolve '{relative_name}': "
                    f"too many parent levels for base package '{base_package}'"
                )
            package_parts = package_parts[:-levels_up]

        if remainder:
            return ".".join(package_parts) + "." + remainder
        return ".".join(package_parts)

    def _resolve_relative_packages(
        self,
        packages: PackageOrIterable | None,
        caller_package: str | None,
    ) -> list[Package]:
        """Resolve relative package names to absolute names."""
        if packages is None:
            return []

        if isinstance(packages, (ModuleType, str)):
            packages = [packages]

        resolved: list[Package] = []
        for package in packages:
            if isinstance(package, ModuleType):
                resolved.append(package)
            elif not package.startswith("."):
                resolved.append(package)
            else:
                if caller_package is None:
                    raise ValueError(
                        "Cannot use relative package paths: "
                        "unable to determine caller package. "
                        "Use absolute package names instead."
                    )
                resolved.append(self._resolve_relative_name(package, caller_package))

        return resolved

    def _normalize_ignore(self, ignore: PackageOrIterable | None) -> tuple[str, ...]:
        """Normalize ignore parameter to a tuple of module name prefixes."""
        if ignore is None:
            return ()

        if isinstance(ignore, (ModuleType, str)):
            ignore = [ignore]

        prefixes: list[str] = []
        for item in ignore:
            name = item.__name__ if isinstance(item, ModuleType) else item
            prefixes.append(name)
            prefixes.append(name + ".")  # For startswith check
        return tuple(prefixes)

    def _should_ignore_module(
        self, module_name: str, ignore_prefixes: tuple[str, ...]
    ) -> bool:
        """Check if a module should be ignored based on ignore prefixes."""
        return module_name.startswith(ignore_prefixes) if ignore_prefixes else False

    def _iter_modules(
        self, packages: Iterable[Package], *, ignore_prefixes: tuple[str, ...]
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
