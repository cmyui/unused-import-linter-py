"""Cross-file import analysis."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from remove_unused_imports._data import ImplicitReexport
from remove_unused_imports._data import ImportInfo
from remove_unused_imports._detection import find_unused_imports
from remove_unused_imports._graph import ImportGraph


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


class CrossFileAnalyzer:
    """Analyze imports across multiple files."""

    def __init__(self, graph: ImportGraph) -> None:
        self.graph = graph

    def analyze(self) -> CrossFileResult:
        """Run cross-file analysis.

        Steps:
        1. Run single-file analysis on each module
        2. Identify which imports are re-exported to other files
        3. Mark re-exported imports as "used" (not unused)
        4. Find implicit re-exports (re-exported but not in __all__)
        5. Aggregate external module usage
        6. Find circular imports
        """
        result = CrossFileResult()

        # Step 1: Get single-file unused imports for each module
        single_file_unused = self._get_single_file_unused()

        # Step 2: Find re-exported imports (imports used by other files)
        reexported = self._find_reexported_imports()

        # Step 3: Filter out re-exported imports from unused list
        for file_path, unused in single_file_unused.items():
            reexported_names = reexported.get(file_path, set())
            truly_unused = [
                imp for imp in unused
                if imp.name not in reexported_names
            ]
            if truly_unused:
                result.unused_imports[file_path] = truly_unused

        # Step 4: Find implicit re-exports
        result.implicit_reexports = self._find_implicit_reexports(reexported)

        # Step 5: Aggregate external usage
        result.external_usage = self._aggregate_external_usage()

        # Step 6: Find circular imports
        result.circular_imports = self.graph.find_cycles()

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

    def _find_reexported_imports(self) -> dict[Path, set[str]]:
        """Find imports that are re-exported to other files.

        Returns a mapping of file -> set of import names that are used
        by other files importing from this file.
        """
        reexported: dict[Path, set[str]] = defaultdict(set)

        for edge in self.graph.edges:
            if edge.is_external or edge.imported is None:
                continue

            # edge.imported is being imported by edge.importer
            # edge.names are the names being imported
            imported_file = edge.imported
            imported_names = edge.names

            if imported_file not in self.graph.nodes:
                continue

            module_info = self.graph.nodes[imported_file]

            # Check which imported names are actually import statements
            # in the imported file (not defined there)
            import_names_in_file = {imp.name for imp in module_info.imports}
            defined_in_file = module_info.defined_names

            for name in imported_names:
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


def analyze_cross_file(graph: ImportGraph) -> CrossFileResult:
    """Convenience function for cross-file analysis."""
    analyzer = CrossFileAnalyzer(graph)
    return analyzer.analyze()
