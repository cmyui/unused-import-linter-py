"""Cross-file import analysis."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from import_analyzer._ast_helpers import AttributeAccessCollector
from import_analyzer._ast_helpers import ImportExtractor
from import_analyzer._ast_helpers import collect_dunder_all_names
from import_analyzer._data import ImplicitReexport
from import_analyzer._data import ImportEdge
from import_analyzer._data import ImportInfo
from import_analyzer._data import IndirectAttributeAccess
from import_analyzer._data import IndirectImport
from import_analyzer._data import ModuleInfo
from import_analyzer._detection import find_unused_imports
from import_analyzer._graph import DefinitionCollector
from import_analyzer._graph import ImportGraph
from import_analyzer._resolution import ModuleResolver


@dataclass
class CrossFileResult:
    """Results of cross-file import analysis."""

    # Unused imports per file (after accounting for re-exports)
    unused_imports: dict[Path, list[ImportInfo]] = field(default_factory=dict)

    # Imports used by other files but not in __all__
    implicit_reexports: list[ImplicitReexport] = field(default_factory=list)

    # Imports going through re-exporters instead of direct sources
    indirect_imports: list[IndirectImport] = field(default_factory=list)

    # Attribute accesses going through re-exporters (e.g., models.LOGGER)
    indirect_attr_accesses: list[IndirectAttributeAccess] = field(default_factory=list)

    # External module usage across the project: module -> files using it
    external_usage: dict[str, set[Path]] = field(default_factory=dict)

    # Circular import chains
    circular_imports: list[list[Path]] = field(default_factory=list)

    # Files that become unreachable when unused imports are removed
    unreachable_files: set[Path] = field(default_factory=set)


class CrossFileAnalyzer:
    """Analyze imports across multiple files."""

    def __init__(
        self,
        graph: ImportGraph,
        entry_point: Path | None = None,
        include_same_package_indirect: bool = False,
    ) -> None:
        self.graph = graph
        self.entry_point = entry_point
        self.include_same_package_indirect = include_same_package_indirect

    def analyze(self) -> CrossFileResult:
        """Run cross-file analysis.

        Steps:
        1. Run single-file analysis on each module
        2. Identify "implicit-reexport-only" imports (__init__.py without __all__)
        3. Compute full cascade of unused imports (iterate until stable)
        4. Find implicit re-exports (re-exported but not in __all__)
        5. Aggregate external module usage
        6. Find circular imports

        The cascade computation handles:
        - Re-export chains: A imports X from B (unused in A), B imports X from C
        - File reachability: removing module imports makes files unreachable

        When a file becomes unreachable from the entry point, imports from that
        file no longer count as "consumers" of re-exports.

        Note: Imports listed in __all__ are considered "used" (public API) and
        are never flagged as unused. This matches the behavior of other linters
        like flake8, ruff, and autoflake.
        """
        result = CrossFileResult()

        # Step 1: Get single-file unused imports for each module
        single_file_unused = self._get_single_file_unused()

        # Step 2: Get "implicit-reexport-only" imports (__init__.py without __all__)
        implicit_reexport_only = self._get_implicit_reexport_only_imports(
            single_file_unused,
        )

        # Step 3: Compute full cascade of unused imports
        all_removed: dict[Path, set[str]] = defaultdict(set)
        unreachable_files: set[Path] = set()

        changed = True
        while changed:
            changed = False

            # Update file reachability based on removed imports
            if self.entry_point:
                unreachable_files = self._find_unreachable_files(all_removed)

            # Find re-exports, excluding unreachable files as consumers
            reexported = self._find_reexported_imports(
                removed_imports=all_removed,
                unreachable_files=unreachable_files,
            )

            # Check imports that are unused locally
            for file_path, unused in single_file_unused.items():
                reexported_names = reexported.get(file_path, set())
                for imp in unused:
                    if imp.name not in reexported_names:
                        if imp.name not in all_removed[file_path]:
                            all_removed[file_path].add(imp.name)
                            changed = True

            # Check "implicit-reexport-only" imports (__init__.py without __all__)
            for file_path, implicit_imports in implicit_reexport_only.items():
                reexported_names = reexported.get(file_path, set())
                for imp in implicit_imports:
                    if imp.name not in reexported_names:
                        if imp.name not in all_removed[file_path]:
                            all_removed[file_path].add(imp.name)
                            changed = True

        # Build unused_imports from the stable removed set
        for file_path, removed_names in all_removed.items():
            unused_imports: list[ImportInfo] = []

            # Add from single-file unused
            for imp in single_file_unused.get(file_path, []):
                if imp.name in removed_names:
                    unused_imports.append(imp)

            # Add from implicit-reexport-only
            for imp in implicit_reexport_only.get(file_path, []):
                if imp.name in removed_names:
                    unused_imports.append(imp)

            if unused_imports:
                # Sort by line number for consistent output
                unused_imports.sort(key=lambda x: (x.lineno, x.name))
                result.unused_imports[file_path] = unused_imports

        # Step 5: Find implicit re-exports (using final reexported state)
        final_reexported = self._find_reexported_imports(
            removed_imports=all_removed,
            unreachable_files=unreachable_files,
        )
        result.implicit_reexports = self._find_implicit_reexports(final_reexported)

        # Step 6: Aggregate external usage
        result.external_usage = self._aggregate_external_usage()

        # Step 7: Find circular imports
        result.circular_imports = self.graph.find_cycles()

        # Step 8: Store truly unreachable files for user warning
        # Filter to only files that are truly dead code (no reachable ancestors)
        truly_unreachable = self._filter_truly_unreachable(
            unreachable_files, all_removed,
        )
        result.unreachable_files = truly_unreachable - {self.entry_point}

        # Step 9: Find indirect imports (imports through re-exporters)
        result.indirect_imports = self._find_indirect_imports()

        # Step 10: Find indirect attribute accesses (module.attr through re-exporters)
        result.indirect_attr_accesses = self._find_indirect_attr_accesses()

        return result

    def _get_single_file_unused(self) -> dict[Path, list[ImportInfo]]:
        """Run single-file unused detection on each module."""
        result: dict[Path, list[ImportInfo]] = {}

        for file_path, module_info in self.graph.nodes.items():
            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            unused = find_unused_imports(source)
            if unused:
                result[file_path] = unused

        return result

    def _get_implicit_reexport_only_imports(
        self,
        single_file_unused: dict[Path, list[ImportInfo]],
    ) -> dict[Path, list[ImportInfo]]:
        """Find imports in __init__.py that exist solely for implicit re-export.

        These are imports that:
        1. Are in an __init__.py file without __all__
        2. Are not used locally (would be flagged by single-file analysis)
        3. Are being re-exported to other files

        Unlike explicit __all__ re-exports, these are implicitly available
        to importers. When no one imports them anymore, they become unused.
        """
        result: dict[Path, list[ImportInfo]] = {}

        for file_path, module_info in self.graph.nodes.items():
            # Only consider __init__.py files without __all__
            if not module_info.is_package:
                continue
            if module_info.exports:  # Has __all__
                continue

            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Get import names and their ImportInfo objects
            import_by_name = {imp.name: imp for imp in module_info.imports}
            defined_names = module_info.defined_names

            # Names already flagged as unused locally
            unused_locally = {imp.name for imp in single_file_unused.get(file_path, [])}

            # Find candidates: is an import, not defined, not already unused
            candidates = set(import_by_name.keys()) - defined_names - unused_locally

            if not candidates:
                continue

            # Check which candidates are actually used locally
            unused_without_all = find_unused_imports(source, ignore_all=True)
            unused_without_all_names = {imp.name for imp in unused_without_all}

            # Implicit-reexport-only: would be unused if we checked locally
            implicit_reexport_names = candidates & unused_without_all_names

            if implicit_reexport_names:
                implicit_imports = [
                    import_by_name[name]
                    for name in implicit_reexport_names
                    if name in import_by_name
                ]
                if implicit_imports:
                    result[file_path] = implicit_imports

        return result

    def _find_unreachable_files(
        self,
        removed_imports: dict[Path, set[str]],
    ) -> set[Path]:
        """Find files that become unreachable when certain imports are removed.

        An edge is considered removed when ALL names from that import are removed.

        Returns files with no remaining import edges - used for cascade detection.
        For user-facing warnings, use _filter_truly_unreachable() to exclude files
        that could still be accessed via parent package imports.
        """
        if not self.entry_point:
            return set()

        # Build set of excluded edges
        excluded_edges: set[tuple[Path, str]] = set()

        for edge in self.graph.edges:
            if edge.is_external or edge.imported is None:
                continue

            removed_names = removed_imports.get(edge.importer, set())
            # If all imported names are removed, the edge is removed
            if edge.names and edge.names <= removed_names:
                excluded_edges.add((edge.importer, edge.module_name))

        # Find reachable files
        reachable = self.graph.find_reachable_files(self.entry_point, excluded_edges)

        # Return unreachable files (for cascade detection)
        return set(self.graph.nodes.keys()) - reachable

    def _filter_truly_unreachable(
        self,
        unreachable_files: set[Path],
        removed_imports: dict[Path, set[str]],
    ) -> set[Path]:
        """Filter unreachable files to only those that are truly dead code.

        A file is only "truly unreachable" if:
        1. It has no remaining import edges pointing to it
        2. None of its ancestor packages are reachable (because Python allows
           accessing submodules via attribute access on parent packages, e.g.,
           `import pkg` then `pkg.submodule.func()`)

        This is used for user-facing warnings about dead code.
        """
        if not self.entry_point:
            return set()

        # Recompute reachable files for ancestor checking
        excluded_edges: set[tuple[Path, str]] = set()
        for edge in self.graph.edges:
            if edge.is_external or edge.imported is None:
                continue
            removed_names = removed_imports.get(edge.importer, set())
            if edge.names and edge.names <= removed_names:
                excluded_edges.add((edge.importer, edge.module_name))

        reachable = self.graph.find_reachable_files(self.entry_point, excluded_edges)

        # Filter to only files with no reachable ancestors
        truly_unreachable: set[Path] = set()
        for file_path in unreachable_files:
            if not self._has_reachable_ancestor(file_path, reachable):
                truly_unreachable.add(file_path)

        return truly_unreachable

    def _has_reachable_ancestor(self, file_path: Path, reachable: set[Path]) -> bool:
        """Check if any ancestor package of file_path is in the reachable set."""
        # Walk up the directory tree looking for __init__.py files
        # Use resolve() to ensure consistent path comparison across platforms
        current = file_path.resolve().parent
        while current != current.parent:  # Stop at filesystem root
            init_file = (current / "__init__.py").resolve()
            if init_file in reachable:
                return True
            current = current.parent
        return False

    def _find_reexported_imports(
        self,
        removed_imports: dict[Path, set[str]] | None = None,
        unreachable_files: set[Path] | None = None,
    ) -> dict[Path, set[str]]:
        """Find imports that are re-exported to other files.

        Args:
            removed_imports: Imports to consider as "virtually removed".
                When checking if file B's import is re-exported via file A,
                skip if A's import of that name is in this set.
            unreachable_files: Files to consider as unreachable from entry point.
                Imports from these files don't count as consumers.

        Returns a mapping of file -> set of import names that are used
        by other files importing from this file.
        """
        removed = removed_imports or {}
        unreachable = unreachable_files or set()
        reexported: dict[Path, set[str]] = defaultdict(set)

        for edge in self.graph.edges:
            if edge.is_external or edge.imported is None:
                continue

            # Skip if the importer is unreachable (its imports don't count)
            if edge.importer in unreachable:
                continue

            # edge.imported is being imported by edge.importer
            # edge.names are the names being imported
            imported_file = edge.imported
            imported_names = edge.names

            # Filter out names that are "virtually removed" from the importer
            importer_removed = removed.get(edge.importer, set())
            active_names = imported_names - importer_removed

            if not active_names:
                continue

            if imported_file not in self.graph.nodes:
                continue

            module_info = self.graph.nodes[imported_file]

            # Check which imported names are actually import statements
            # in the imported file (not defined there)
            import_names_in_file = {imp.name for imp in module_info.imports}
            defined_in_file = module_info.defined_names

            for name in active_names:
                # If the name is an import in the target file (not defined),
                # then it's being re-exported
                if name in import_names_in_file and name not in defined_in_file:
                    reexported[imported_file].add(name)

        return dict(reexported)

    def _find_implicit_reexports(
        self,
        reexported: dict[Path, set[str]],
    ) -> list[ImplicitReexport]:
        """Find imports that are re-exported but not in __all__."""
        result: list[ImplicitReexport] = []

        for file_path, reexported_names in reexported.items():
            if file_path not in self.graph.nodes:
                continue

            module_info = self.graph.nodes[file_path]
            exports = module_info.exports  # Names in __all__

            for name in reexported_names:
                # If re-exported but not in __all__, it's implicit
                if name not in exports:
                    # Find which files use this re-exported name
                    used_by: set[Path] = set()
                    for edge in self.graph.get_importers(file_path):
                        if name in edge.names:
                            used_by.add(edge.importer)

                    result.append(
                        ImplicitReexport(
                            source_file=file_path,
                            import_name=name,
                            used_by=used_by,
                        ),
                    )

        return result

    def _aggregate_external_usage(self) -> dict[str, set[Path]]:
        """Aggregate which files use which external modules."""
        usage: dict[str, set[Path]] = defaultdict(set)

        for edge in self.graph.edges:
            if edge.is_external:
                usage[edge.module_name].add(edge.importer)

        return dict(usage)

    def _find_indirect_imports(self) -> list[IndirectImport]:
        """Find imports that go through re-exporters instead of direct sources.

        An indirect import is when file A imports name X from file B,
        but B doesn't define X - it imports X from file C.

        By default, same-package re-exports are allowed (e.g., pkg/__init__.py
        re-exporting from pkg/module.py). Use include_same_package_indirect=True
        to flag those as well.
        """
        results: list[IndirectImport] = []

        for edge in self.graph.edges:
            if edge.is_external or edge.imported is None:
                continue

            imported_module = self.graph.nodes.get(edge.imported)
            if not imported_module:
                continue

            # For each name imported from this module
            for name in edge.names:
                # Check if this name is a re-export (import, not definition)
                if name in imported_module.defined_names:
                    continue  # Defined here, not indirect

                # Find where this module got the name from (and original name)
                trace_result = self._trace_import_source(edge.imported, name)
                if trace_result is None:
                    continue  # Can't trace
                original_source, original_name = trace_result
                if original_source == edge.imported:
                    continue  # Already at source

                # Check if same-package re-export
                is_same_pkg = self._is_same_package_reexport(
                    edge.imported,
                    original_source,
                )

                if is_same_pkg and not self.include_same_package_indirect:
                    continue  # Skip same-package re-exports by default

                # Find the line number for this import
                lineno = self._find_import_lineno(edge.importer, edge.imported, name)

                results.append(
                    IndirectImport(
                        file=edge.importer,
                        name=name,
                        original_name=original_name,
                        lineno=lineno,
                        current_source=edge.imported,
                        original_source=original_source,
                        is_same_package=is_same_pkg,
                    ),
                )

        # Sort by file, then line number for consistent output
        results.sort(key=lambda x: (x.file, x.lineno, x.name))
        return results

    def _trace_import_source(
        self,
        file: Path,
        name: str,
    ) -> tuple[Path, str] | None:
        """Trace an import back to its original definition.

        Follows the import chain until we find a file that actually defines
        the name (not just re-exports it). Handles aliases along the way.

        Returns:
            Tuple of (source_file, original_name) where original_name is the
            name as defined in source_file (may differ from input name if
            aliases were used in the chain). Returns None if can't trace.
        """
        visited: set[Path] = set()
        current = file
        current_name = name

        while current not in visited:
            visited.add(current)
            module = self.graph.nodes.get(current)
            if not module:
                return None

            # If defined here, this is the source
            if current_name in module.defined_names:
                return (current, current_name)

            # Find where this module imports the name from
            found_next = False
            for imp in module.imports:
                if imp.name == current_name:
                    # Follow the original_name if aliased
                    next_name = imp.original_name
                    # Find the edge for this import
                    for edge in self.graph.get_imports(current):
                        if current_name in edge.names and edge.imported:
                            current = edge.imported
                            current_name = next_name
                            found_next = True
                            break
                    break

            if not found_next:
                return None  # Can't trace further

        return None  # Circular, can't determine

    def _is_same_package_reexport(self, reexporter: Path, source: Path) -> bool:
        """Check if reexporter is __init__.py re-exporting from its own package.

        Returns True if:
        1. reexporter is an __init__.py file, AND
        2. source is within the same package directory

        This pattern is acceptable because __init__.py commonly defines
        the public API of a package by re-exporting from submodules.
        """
        if reexporter.name != "__init__.py":
            return False

        # Get the package directory (parent of __init__.py)
        pkg_dir = reexporter.parent.resolve()
        source_resolved = source.resolve()

        # Check if source is within the package directory
        try:
            source_resolved.relative_to(pkg_dir)
            return True
        except ValueError:
            return False

    def _find_indirect_attr_accesses(self) -> list[IndirectAttributeAccess]:
        """Find attribute accesses that go through re-exporters.

        Handles nested access like pkg.mod.LOGGER where:
        1. pkg resolves to some module
        2. mod could be a submodule or re-exported module
        3. LOGGER is the final attribute to check for indirect access

        For each usage, traces through the chain to find if the final
        attribute is re-exported from another source.
        """
        results: list[IndirectAttributeAccess] = []

        # Iterate over a copy of the keys since we may add new nodes during iteration
        for file_path in list(self.graph.nodes.keys()):
            module_info = self.graph.nodes[file_path]
            # Find 'import X' or 'import X as Y' style imports
            # imp.name = bound name (alias if present), imp.original_name = actual module
            module_imports: dict[str, ImportInfo] = {}
            for imp in module_info.imports:
                if not imp.is_from_import:
                    module_imports[imp.name] = imp

            if not module_imports:
                continue

            # Parse file and collect attribute usages
            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue

            collector = AttributeAccessCollector(set(module_imports.keys()))
            collector.visit(tree)

            # For each root import and its usages
            for bound_name, usages in collector.usages.items():
                if not usages:
                    continue

                imp = module_imports[bound_name]

                # Find the resolved module file for the root import
                root_module_path: Path | None = None
                for edge in self.graph.get_imports(file_path):
                    if edge.module_name == imp.original_name and edge.imported:
                        root_module_path = edge.imported
                        break

                if not root_module_path:
                    continue

                # Group usages by attr_path (as tuple for hashability)
                by_path: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(
                    list,
                )
                for u in usages:
                    path_key = tuple(u.attr_path)
                    by_path[path_key].append((u.lineno, u.col_offset))

                for attr_path_tuple, usage_locs in by_path.items():
                    attr_path = list(attr_path_tuple)
                    if not attr_path:
                        continue

                    # Resolve through the path to find the final module
                    # and check if the final attribute is indirect
                    result = self._resolve_attr_path(root_module_path, attr_path)
                    if result is None:
                        continue

                    final_module, final_attr, original_source, original_name = result

                    # If original source is the same as final module, it's direct
                    if original_source == final_module:
                        continue

                    # Check same-package re-export
                    is_same_pkg = self._is_same_package_reexport(
                        final_module,
                        original_source,
                    )

                    if is_same_pkg and not self.include_same_package_indirect:
                        continue

                    results.append(
                        IndirectAttributeAccess(
                            file=file_path,
                            import_name=bound_name,
                            import_lineno=imp.lineno,
                            attr_path=attr_path,
                            attr_name=final_attr,
                            original_name=original_name,
                            usages=usage_locs,
                            current_source=final_module,
                            original_source=original_source,
                            is_same_package=is_same_pkg,
                        ),
                    )

        # Sort by file, then line number, then attr path for consistent output
        results.sort(key=lambda x: (x.file, x.import_lineno, tuple(x.attr_path)))
        return results

    def _resolve_attr_path(
        self,
        start_module: Path,
        attr_path: list[str],
    ) -> tuple[Path, str, Path, str] | None:
        """Resolve an attribute path through modules.

        For pkg.mod.LOGGER with start_module=pkg/__init__.py and attr_path=['mod', 'LOGGER']:
        1. Resolve 'mod' - could be submodule pkg/mod or re-exported in pkg/__init__.py
        2. Resolve 'LOGGER' in that module - check if direct or re-exported

        Returns:
            (final_module, final_attr, original_source, original_name) or None if can't resolve.
            final_module: The module where the final attribute is accessed
            final_attr: The final attribute name (last in path)
            original_source: Where it's actually defined
            original_name: The name in original_source (may differ due to aliases)
        """
        if not attr_path:
            return None

        current_module = start_module
        current_module_info = self.graph.nodes.get(current_module)
        if not current_module_info:
            return None

        # Walk through intermediate attributes (all except the last)
        for attr in attr_path[:-1]:
            next_module = self._resolve_module_attr(current_module, attr)
            if next_module is None:
                return None
            current_module = next_module
            current_module_info = self.graph.nodes.get(current_module)
            if not current_module_info:
                return None

        # Now check the final attribute
        final_attr = attr_path[-1]

        # Is it defined in the current module?
        if final_attr in current_module_info.defined_names:
            # Direct access - return current module as both final and original
            return (current_module, final_attr, current_module, final_attr)

        # Try to trace to original source
        trace_result = self._trace_import_source(current_module, final_attr)
        if trace_result is None:
            return None

        original_source, original_name = trace_result
        return (current_module, final_attr, original_source, original_name)

    def _resolve_module_attr(self, module_path: Path, attr: str) -> Path | None:
        """Resolve an attribute that should be a module.

        For pkg/__init__.py and attr='mod', looks for:
        1. Submodule: pkg/mod/__init__.py or pkg/mod.py
        2. Re-exported module in pkg/__init__.py

        Returns the resolved module path or None.
        """
        module_info = self.graph.nodes.get(module_path)
        if not module_info:
            return None

        # Determine the package directory
        # For __init__.py, the package dir is the parent directory
        # For regular .py files, they can't have submodules, so we skip submodule check
        if module_path.name == "__init__.py":
            pkg_dir = module_path.parent
        else:
            # Regular .py files can't have submodules accessible as attributes
            # but could still have re-exported modules
            pkg_dir = None

        # Check if it's a submodule (only for __init__.py files)
        # Note: submodules may not be in the graph if not explicitly imported,
        # so we check on disk and add them dynamically
        if pkg_dir is not None:
            submodule_dir = pkg_dir / attr / "__init__.py"
            submodule_file_py = pkg_dir / f"{attr}.py"

            # Check for submodule directory (pkg/attr/__init__.py)
            if submodule_dir.exists():
                # Add to graph if not present
                if submodule_dir not in self.graph.nodes:
                    self._add_module_to_graph(submodule_dir)
                if submodule_dir in self.graph.nodes:
                    return submodule_dir

            # Check for submodule file (pkg/attr.py)
            if submodule_file_py.exists():
                # Add to graph if not present
                if submodule_file_py not in self.graph.nodes:
                    self._add_module_to_graph(submodule_file_py)
                if submodule_file_py in self.graph.nodes:
                    return submodule_file_py

        # Check if attr is imported/re-exported in the module and is a module itself
        # Look for imports like "from .submod import something" or "import submod"
        for imp in module_info.imports:
            if imp.name == attr:
                # Find where this import resolves to
                for edge in self.graph.get_imports(module_path):
                    if attr in edge.names and edge.imported:
                        # Check if the imported thing is itself a module
                        if edge.imported in self.graph.nodes:
                            return edge.imported
                        break

        return None

    def _add_module_to_graph(self, file_path: Path) -> None:
        """Add a module to the graph dynamically.

        This is used when we discover submodules that weren't explicitly imported
        but are accessed via attribute syntax (e.g., pkg.submod.attr).
        """
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            return

        # Extract imports
        extractor = ImportExtractor()
        extractor.visit(tree)
        imports = extractor.imports

        # Extract defined names
        def_collector = DefinitionCollector()
        def_collector.visit(tree)
        defined_names = def_collector.defined_names

        # Extract __all__ if present
        exports = collect_dunder_all_names(tree)

        # Create module info
        # Compute module name based on file path relative to graph root
        # For simplicity, use the file stem as module name
        if file_path.name == "__init__.py":
            module_name = file_path.parent.name
            is_package = True
        else:
            module_name = file_path.stem
            is_package = False

        module_info = ModuleInfo(
            file_path=file_path,
            module_name=module_name,
            is_package=is_package,
            imports=imports,
            exports=exports,
            defined_names=defined_names,
        )

        self.graph.nodes[file_path] = module_info

        # Also process imports and add edges
        # Use the entry point to create the resolver so it has the correct source root
        # If no entry point, fall back to file's parent (may not resolve relative imports correctly)
        resolver_entry = self.entry_point if self.entry_point else file_path
        resolver = ModuleResolver(resolver_entry)

        for imp in imports:
            if imp.is_from_import:
                module_name_to_resolve = imp.module
                names = {imp.name}
                level = imp.level
            else:
                module_name_to_resolve = imp.original_name
                names = {imp.name}
                level = imp.level

            # Resolve the import
            resolved = resolver.resolve_import(module_name_to_resolve, file_path, level)
            is_external = resolved is None and resolver.is_external(
                module_name_to_resolve,
            )

            edge = ImportEdge(
                importer=file_path,
                imported=resolved,
                module_name=module_name_to_resolve,
                names=names,
                is_external=is_external,
                level=level,
            )
            self.graph.add_edge(edge)

            # If resolved to a local file not in graph, add it recursively
            if resolved and resolved not in self.graph.nodes:
                self._add_module_to_graph(resolved)

    def _find_import_lineno(
        self,
        importer: Path,
        imported: Path,
        name: str,
    ) -> int:
        """Find the line number of a specific import in a file."""
        module = self.graph.nodes.get(importer)
        if not module:
            return 0

        # Look for the import that matches both the source and name
        for imp in module.imports:
            if imp.name == name:
                # Verify this import is from the right module
                for edge in self.graph.get_imports(importer):
                    if edge.imported == imported and name in edge.names:
                        return imp.lineno

        return 0


def analyze_cross_file(
    graph: ImportGraph,
    entry_point: Path | None = None,
    include_same_package_indirect: bool = False,
) -> CrossFileResult:
    """Convenience function for cross-file analysis."""
    analyzer = CrossFileAnalyzer(graph, entry_point, include_same_package_indirect)
    return analyzer.analyze()
