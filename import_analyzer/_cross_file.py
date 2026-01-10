"""Cross-file import analysis."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from import_analyzer._data import ImplicitReexport
from import_analyzer._data import ImportInfo
from import_analyzer._detection import find_unused_imports
from import_analyzer._graph import ImportGraph


@dataclass
class CrossFileResult:
    """Results of cross-file import analysis."""

    # Unused imports per file (after accounting for re-exports)
    unused_imports: dict[Path, list[ImportInfo]] = field(default_factory=dict)

    # Imports used by other files but not in __all__
    implicit_reexports: list[ImplicitReexport] = field(default_factory=list)

    # External module usage across the project: module -> files using it
    external_usage: dict[str, set[Path]] = field(default_factory=dict)

    # Circular import chains
    circular_imports: list[list[Path]] = field(default_factory=list)

    # Files that become unreachable when unused imports are removed
    unreachable_files: set[Path] = field(default_factory=set)


class CrossFileAnalyzer:
    """Analyze imports across multiple files."""

    def __init__(self, graph: ImportGraph, entry_point: Path | None = None) -> None:
        self.graph = graph
        self.entry_point = entry_point

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
        truly_unreachable = self._filter_truly_unreachable(unreachable_files, all_removed)
        result.unreachable_files = truly_unreachable - {self.entry_point}

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
            unused_locally = {
                imp.name for imp in single_file_unused.get(file_path, [])
            }

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
        self, reexported: dict[Path, set[str]],
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


def analyze_cross_file(
    graph: ImportGraph, entry_point: Path | None = None,
) -> CrossFileResult:
    """Convenience function for cross-file analysis."""
    analyzer = CrossFileAnalyzer(graph, entry_point)
    return analyzer.analyze()
