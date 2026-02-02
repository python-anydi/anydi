"""Graph generation for AnyDI."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from typing_extensions import type_repr

from ._provider import Provider

if TYPE_CHECKING:
    from ._container import Container


class Graph:
    """Graph generator for the dependency container."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _get_aliases_for(self, dependency_type: Any) -> list[str]:
        """Get list of alias names that point to a dependency type."""
        return [
            type_repr(alias).rsplit(".", 1)[-1]
            for alias in self._container.get_aliases_for(dependency_type)
        ]

    def draw(
        self,
        output_format: Literal["tree", "mermaid", "dot", "json"] = "tree",
        *,
        full_path: bool = False,
        **kwargs: Any,
    ) -> str:
        """Draw the dependency graph."""
        if output_format == "mermaid":
            return self._mermaid(full_path=full_path)
        if output_format == "dot":
            return self._dot(full_path=full_path)
        if output_format == "json":
            return self._json(full_path=full_path, ident=kwargs.get("ident", 2))
        return self._tree(full_path=full_path)

    def _mermaid(self, full_path: bool) -> str:
        """Generate mermaid format dependency graph."""
        lines: list[str] = ["graph TD"]
        seen_nodes: set[str] = set()

        for provider in self._container.providers.values():
            dependency_repr = self._get_name(provider, full_path)
            scope_label = self._get_scope_label(provider.scope, provider.from_context)
            node_id = dependency_repr.replace(".", "_")

            if node_id not in seen_nodes:
                seen_nodes.add(node_id)

            for param in provider.parameters:
                if param.provider is None:
                    continue

                dep_name = self._get_name(param.provider, full_path)
                dep_scope = self._get_scope_label(
                    param.provider.scope, param.provider.from_context
                )
                dep_node_id = dep_name.replace(".", "_")

                if dep_node_id not in seen_nodes:
                    seen_nodes.add(dep_node_id)

                # Use dashed line for from_context dependencies
                if param.provider.from_context:
                    arrow = "-.->"
                else:
                    arrow = "-->"

                lines.append(
                    f'    {node_id}["{dependency_repr} ({scope_label})"] '
                    f"{arrow}|{param.name}| "
                    f'{dep_node_id}["{dep_name} ({dep_scope})"]'
                )

        return "\n".join(lines)

    def _dot(self, full_path: bool) -> str:
        """Generate DOT format dependency graph."""
        lines: list[str] = ["digraph G {"]
        lines.append("    node [shape=box];")
        seen_edges: set[tuple[str, str]] = set()

        for provider in self._container.providers.values():
            provider_name = self._get_name(provider, full_path)
            scope_label = self._get_scope_label(provider.scope, provider.from_context)
            node_id = f'"{provider_name} ({scope_label})"'

            for param in provider.parameters:
                if param.provider is None:
                    continue

                dep_name = self._get_name(param.provider, full_path)
                dep_scope = self._get_scope_label(
                    param.provider.scope, param.provider.from_context
                )
                dep_node_id = f'"{dep_name} ({dep_scope})"'

                if (node_id, dep_node_id) not in seen_edges:
                    style = " [style=dashed]" if param.provider.from_context else ""
                    lines.append(
                        f'    {node_id} -> {dep_node_id} [label="{param.name}"]{style};'
                    )
                    seen_edges.add((node_id, dep_node_id))

        lines.append("}")
        return "\n".join(lines)

    def _json(self, full_path: bool, ident: int) -> str:
        """Generate JSON format dependency graph."""
        container_type = type(self._container)
        providers: list[dict[str, Any]] = []

        for provider in self._container.providers.values():
            # Exclude Container itself
            if provider.dependency_type is container_type:
                continue

            dependencies: list[dict[str, str]] = []
            for param in provider.parameters:
                if param.provider is None:
                    continue
                dependencies.append(
                    {
                        "name": param.name,
                        "type": self._get_name(param.provider, full_path),
                    }
                )

            aliases = self._get_aliases_for(provider.dependency_type)
            provider_data: dict[str, Any] = {
                "type": self._get_name(provider, full_path),
                "scope": provider.scope,
                "from_context": provider.from_context,
                "dependencies": dependencies,
            }
            if aliases:
                provider_data["aliases"] = aliases
            providers.append(provider_data)

        return json.dumps({"providers": providers}, indent=ident)

    def _tree(self, full_path: bool) -> str:
        """Generate tree format dependency graph."""
        lines: list[str] = []

        # Find all dependency types (providers that are dependencies of others)
        all_deps: set[Any] = set()
        for provider in self._container.providers.values():
            for param in provider.parameters:
                if param.provider is not None:
                    all_deps.add(param.provider.dependency_type)

        # Root providers: not a dependency of any other provider
        # Exclude Container itself (internal implementation detail)
        container_type = type(self._container)
        root_providers = [
            p
            for p in self._container.providers.values()
            if p.dependency_type not in all_deps
            and p.dependency_type is not container_type
        ]

        for i, provider in enumerate(root_providers):
            if i > 0:
                lines.append("")
            lines.append(self._format_tree_node(provider, full_path))
            self._render_tree_children(provider, "", set(), lines, full_path)

        return "\n".join(lines)

    def _format_tree_node(
        self, provider: Provider, full_path: bool, param_name: str | None = None
    ) -> str:
        name = self._get_name(provider, full_path)
        scope_label = Graph._get_scope_label(provider.scope, provider.from_context)
        context_marker = " [context]" if provider.from_context else ""
        aliases = self._get_aliases_for(provider.dependency_type)
        alias_marker = f" [alias: {', '.join(aliases)}]" if aliases else ""
        if param_name:
            return f"{param_name}: {name} ({scope_label}){context_marker}{alias_marker}"
        return f"{name} ({scope_label}){context_marker}{alias_marker}"

    def _render_tree_children(
        self,
        provider: Provider,
        prefix: str,
        visited: set[Any],
        lines: list[str],
        full_path: bool,
    ) -> None:
        if provider.dependency_type in visited:
            return
        visited = visited | {provider.dependency_type}

        deps = [p for p in provider.parameters if p.provider is not None]
        for i, param in enumerate(deps):
            dep_provider = param.provider
            if dep_provider is None:
                continue
            is_last = i == len(deps) - 1
            connector = "└── " if is_last else "├── "
            node_text = self._format_tree_node(dep_provider, full_path, param.name)
            lines.append(f"{prefix}{connector}{node_text}")
            extension = "    " if is_last else "│   "
            self._render_tree_children(
                dep_provider, prefix + extension, visited, lines, full_path
            )

    @staticmethod
    def _get_name(provider: Provider, full_path: bool) -> str:
        if full_path:
            return type_repr(provider.dependency_type)
        return type_repr(provider.dependency_type).rsplit(".", 1)[-1]

    @staticmethod
    def _get_scope_label(scope: str, from_context: bool) -> str:
        if from_context:
            return f"{scope}/context"
        return scope
