"""Import graph construction and analysis."""
from __future__ import annotations

import ast
from collections import defaultdict
from collections import deque
from pathlib import Path

from import_analyzer._ast_helpers import ImportExtractor
from import_analyzer._ast_helpers import collect_dunder_all_names
from import_analyzer._data import ImportEdge
from import_analyzer._data import ImportInfo
from import_analyzer._data import ModuleInfo
from import_analyzer._resolution import ModuleResolver

# Directories to skip when scanning for Python files
_SKIP_DIRS = frozenset({
    ".venv",
    "venv",
    ".env",
    "env",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
})


def _should_skip_path(path: Path) -> bool:
    """Check if a path should be skipped during analysis."""
    parts = path.parts
    for skip_pattern in _SKIP_DIRS:
        if skip_pattern.startswith("*"):
            # Glob pattern like *.egg-info
            suffix = skip_pattern[1:]
            if any(part.endswith(suffix) for part in parts):
                return True
        elif skip_pattern in parts:
            return True
    return False


class ImportGraph:
    """A graph representing import relationships between modules."""

    def __init__(self) -> None:
        self.nodes: dict[Path, ModuleInfo] = {}
        self.edges: list[ImportEdge] = []
        # Indices for fast lookups
        self._imports_by_file: dict[Path, list[ImportEdge]] = defaultdict(list)
        self._importers_by_file: dict[Path, list[ImportEdge]] = defaultdict(list)

    def add_node(self, module_info: ModuleInfo) -> None:
        """Add a module to the graph."""
        self.nodes[module_info.file_path] = module_info

    def add_edge(self, edge: ImportEdge) -> None:
        """Add an import edge to the graph."""
        self.edges.append(edge)
        self._imports_by_file[edge.importer].append(edge)
        if edge.imported is not None:
            self._importers_by_file[edge.imported].append(edge)

    def get_imports(self, file: Path) -> list[ImportEdge]:
        """Get all imports made by a file."""
        return self._imports_by_file.get(file, [])

    def get_importers(self, file: Path) -> list[ImportEdge]:
        """Get all files that import a given file."""
        return self._importers_by_file.get(file, [])

    def find_cycles(self) -> list[list[Path]]:
        """Find all import cycles using Tarjan's algorithm.

        Returns a list of strongly connected components with more than one node,
        representing circular import chains.
        """
        index_counter = [0]
        stack: list[Path] = []
        lowlink: dict[Path, int] = {}
        index: dict[Path, int] = {}
        on_stack: set[Path] = set()
        sccs: list[list[Path]] = []

        def strongconnect(node: Path) -> None:
            index[node] = index_counter[0]
            lowlink[node] = index_counter[0]
            index_counter[0] += 1
            stack.append(node)
            on_stack.add(node)

            # Consider successors (files we import)
            for edge in self._imports_by_file.get(node, []):
                if edge.imported is None:
                    continue  # Skip external imports
                successor = edge.imported
                if successor not in index:
                    strongconnect(successor)
                    lowlink[node] = min(lowlink[node], lowlink[successor])
                elif successor in on_stack:
                    lowlink[node] = min(lowlink[node], index[successor])

            # If node is root of SCC
            if lowlink[node] == index[node]:
                scc: list[Path] = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == node:
                        break
                # Only keep SCCs with more than one node (actual cycles)
                if len(scc) > 1:
                    sccs.append(scc)

        for node in self.nodes:
            if node not in index:
                strongconnect(node)

        return sccs

    def find_reachable_files(
        self,
        entry_point: Path,
        excluded_edges: set[tuple[Path, str]] | None = None,
    ) -> set[Path]:
        """Find all files reachable from entry point.

        Args:
            entry_point: The starting file for traversal.
            excluded_edges: Set of (importer, module_name) tuples representing
                edges to exclude from traversal (as if those imports were removed).

        Returns:
            Set of file paths reachable from entry point.
        """
        excluded = excluded_edges or set()
        reachable: set[Path] = set()
        queue = deque([entry_point])

        while queue:
            node = queue.popleft()
            if node in reachable:
                continue
            if node not in self.nodes:
                continue
            reachable.add(node)

            # Follow edges that aren't excluded
            for edge in self._imports_by_file.get(node, []):
                if edge.imported is None:
                    continue  # Skip external imports
                # Check if this edge is excluded
                if (edge.importer, edge.module_name) in excluded:
                    continue
                if edge.imported not in reachable:
                    queue.append(edge.imported)

        return reachable

    def topological_order(self) -> list[Path]:
        """Return files in topological order (dependencies first).

        If there are cycles, they are processed as a group. Files in cycles
        are placed together, but their relative order within the cycle is
        arbitrary.
        """
        # Build in-degree map
        in_degree: dict[Path, int] = {node: 0 for node in self.nodes}
        for edge in self.edges:
            if edge.imported is not None and edge.imported in self.nodes:
                in_degree[edge.importer] = in_degree.get(edge.importer, 0)
                # Don't increment for cycles - we'll handle them separately

        # Count actual in-degrees from non-cycle edges
        cycles = self.find_cycles()
        cycle_nodes: set[Path] = set()
        for cycle in cycles:
            cycle_nodes.update(cycle)

        for edge in self.edges:
            if edge.imported is None:
                continue
            if edge.imported not in self.nodes:
                continue
            # Only count if not a cycle edge
            if not (edge.importer in cycle_nodes and edge.imported in cycle_nodes):
                in_degree[edge.importer] += 1

        # Start with nodes that have no dependencies
        result: list[Path] = []
        queue = deque(n for n in self.nodes if in_degree[n] == 0)

        while queue:
            node = queue.popleft()
            result.append(node)

            # Decrease in-degree of dependents
            for edge in self._importers_by_file.get(node, []):
                if edge.importer in in_degree:
                    in_degree[edge.importer] -= 1
                    if in_degree[edge.importer] == 0:
                        queue.append(edge.importer)

        # If we missed any nodes (cycles), add them at the end
        remaining = set(self.nodes.keys()) - set(result)
        result.extend(remaining)

        return result


class DefinitionCollector(ast.NodeVisitor):
    """Collect names defined in a module (classes, functions, variables)."""

    def __init__(self) -> None:
        self.defined_names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defined_names.add(node.name)
        # Don't recurse into function body

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.defined_names.add(node.name)
        # Don't recurse into function body

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defined_names.add(node.name)
        # Don't recurse into class body

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._collect_target_names(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._collect_target_names(node.target)

    def _collect_target_names(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.defined_names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._collect_target_names(elt)


class GraphBuilder:
    """Build an import graph by traversing from an entry point."""

    def __init__(self, entry_point: Path) -> None:
        self.resolver = ModuleResolver(entry_point)
        self.graph = ImportGraph()
        self._visited: set[Path] = set()

    def build(self) -> ImportGraph:
        """Build the complete import graph starting from the entry point."""
        entry_path = self.resolver.entry_point
        self._process_file(entry_path)
        return self.graph

    def build_from_directory(self, directory: Path) -> ImportGraph:
        """Build import graph from all Python files in a directory.

        This is for 'whole project mode' where we analyze all files,
        not just those reachable from an entry point.
        """
        directory = directory.resolve()

        # Find all Python files, skipping common non-source directories
        for py_file in directory.rglob("*.py"):
            if _should_skip_path(py_file):
                continue
            if py_file not in self._visited:
                self._process_file(py_file)

        return self.graph

    def _process_file(self, file_path: Path) -> None:
        """Process a single file and add it to the graph."""
        file_path = file_path.resolve()

        if file_path in self._visited:
            return
        self._visited.add(file_path)

        # Skip files in common non-source directories
        if _should_skip_path(file_path):
            return

        # Read and parse the file
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            return

        # Extract imports
        import_extractor = ImportExtractor()
        import_extractor.visit(tree)

        # Extract defined names
        def_collector = DefinitionCollector()
        def_collector.visit(tree)

        # Extract __all__ exports
        exports = collect_dunder_all_names(tree)

        # Create module info
        module_name = self.resolver.get_module_name(file_path)
        is_package = file_path.name == "__init__.py"

        module_info = ModuleInfo(
            file_path=file_path,
            module_name=module_name,
            is_package=is_package,
            imports=import_extractor.imports,
            exports=exports,
            defined_names=def_collector.defined_names,
        )
        self.graph.add_node(module_info)

        # Process each import and resolve to file paths
        self._process_imports(file_path, import_extractor.imports)

    def _process_imports(
        self, file_path: Path, imports: list[ImportInfo],
    ) -> None:
        """Process imports from a file, resolve them, and add edges."""
        # Group imports by (module, level) to consolidate edges
        import_groups: dict[tuple[str, int], set[str]] = defaultdict(set)

        for imp in imports:
            if imp.is_from_import:
                # from X import Y -> module is X
                key = (imp.module, imp.level)
            else:
                # import X -> module is original_name (the full dotted path)
                key = (imp.original_name, imp.level)
            import_groups[key].add(imp.name)

        # Resolve each unique import
        for (module_name, level), names in import_groups.items():
            resolved = self.resolver.resolve_import(module_name, file_path, level)
            is_external = resolved is None and self.resolver.is_external(module_name)

            edge = ImportEdge(
                importer=file_path,
                imported=resolved,
                module_name=module_name,
                names=names,
                is_external=is_external,
                level=level,
            )
            self.graph.add_edge(edge)

            # If resolved to a local file, process it recursively
            if resolved is not None:
                self._process_file(resolved)

            # For from-imports from packages, also check if imported names are submodules
            # e.g., `from mypkg import submodule` where submodule
            # is a subpackage not explicitly imported in mypkg/__init__.py
            # Only do this for packages (__init__.py), not regular modules
            if (
                resolved is not None
                and not is_external
                and resolved.name == "__init__.py"
            ):
                # Get names available from the __init__.py (imports + definitions)
                init_module = self.graph.nodes.get(resolved)
                init_names: set[str] = set()
                if init_module:
                    init_names = {imp.name for imp in init_module.imports}
                    init_names |= init_module.defined_names

                for name in names:
                    # Only check for submodule if name is NOT already available
                    # from the __init__.py. This handles cases like:
                    # - `from pkg import Foo` where Foo is re-exported in __init__.py
                    # - `from pkg import submodule` where submodule is
                    #   a subpackage NOT imported in __init__.py
                    if name in init_names:
                        continue

                    submodule_name = f"{module_name}.{name}"
                    submodule_resolved = self.resolver.resolve_import(
                        submodule_name, file_path, level,
                    )
                    if submodule_resolved is not None:
                        self._process_file(submodule_resolved)


def build_import_graph(entry_point: Path) -> ImportGraph:
    """Convenience function to build an import graph from an entry point."""
    builder = GraphBuilder(entry_point)
    return builder.build()


def build_import_graph_from_directory(directory: Path) -> ImportGraph:
    """Convenience function to build an import graph from a directory.

    If the directory is a package (has __init__.py), the source root is set
    to the parent directory so that imports like `from package import X`
    resolve correctly when analyzing files inside the package.
    """
    directory = directory.resolve()

    # If directory is a package, use parent as source root
    # This ensures `from package import X` resolves to package/__init__.py
    if (directory / "__init__.py").exists():
        dummy_entry = directory.parent / "__entry__.py"
    else:
        dummy_entry = directory / "__entry__.py"

    builder = GraphBuilder(dummy_entry)
    return builder.build_from_directory(directory)
