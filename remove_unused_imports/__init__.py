from __future__ import annotations

from remove_unused_imports._autofix import remove_unused_imports
from remove_unused_imports._cross_file import CrossFileResult
from remove_unused_imports._cross_file import analyze_cross_file
from remove_unused_imports._data import ImplicitReexport
from remove_unused_imports._data import ImportEdge
from remove_unused_imports._data import ImportInfo
from remove_unused_imports._data import ModuleInfo
from remove_unused_imports._detection import find_unused_imports
from remove_unused_imports._graph import ImportGraph
from remove_unused_imports._graph import build_import_graph
from remove_unused_imports._graph import build_import_graph_from_directory
from remove_unused_imports._main import check_cross_file
from remove_unused_imports._main import check_file
from remove_unused_imports._main import collect_python_files
from remove_unused_imports._main import main
from remove_unused_imports._resolution import ModuleResolver

__all__ = [
    # Data types
    "ImportInfo",
    "ModuleInfo",
    "ImportEdge",
    "ImplicitReexport",
    "CrossFileResult",
    # Single-file analysis
    "find_unused_imports",
    "remove_unused_imports",
    "check_file",
    # Cross-file analysis
    "ModuleResolver",
    "ImportGraph",
    "build_import_graph",
    "build_import_graph_from_directory",
    "analyze_cross_file",
    "check_cross_file",
    # CLI
    "collect_python_files",
    "main",
]
