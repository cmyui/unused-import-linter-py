from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path


@dataclass
class ImportInfo:
    """Information about an import statement."""

    # The name as it appears in code (alias if present, otherwise original)
    name: str
    module: str  # The module being imported from (empty for 'import X')
    original_name: str  # The original name before aliasing
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int
    is_from_import: bool  # True for 'from X import Y', False for 'import X'
    full_node_lineno: int  # Line number of the full import statement
    full_node_end_lineno: int  # End line of the full import statement
    level: int = 0  # Number of dots for relative imports (0 = absolute)


@dataclass
class ModuleInfo:
    """Information about a Python module in the project."""

    file_path: Path
    module_name: str  # "mypackage.submodule.utils"
    is_package: bool  # True for __init__.py
    imports: list[ImportInfo] = field(default_factory=list)
    exports: set[str] = field(default_factory=set)  # Names in __all__
    defined_names: set[str] = field(default_factory=set)  # Classes, functions, vars


@dataclass
class ImportEdge:
    """An edge in the import graph."""

    importer: Path  # File containing the import statement
    imported: Path | None  # Resolved file path, None = external module
    module_name: str  # The module name as written in the import
    names: set[str]  # Names being imported (e.g., {"List", "Dict"})
    is_external: bool  # True if importing from stdlib/third-party
    level: int = 0  # Number of dots for relative imports


@dataclass
class ImplicitReexport:
    """Import used by other files but not in __all__."""

    source_file: Path
    import_name: str
    used_by: set[Path] = field(default_factory=set)


def is_under_path(file_path: Path, base_path: Path) -> bool:
    """Check if a file is under the base path."""
    try:
        file_path.relative_to(base_path)
        return True
    except ValueError:
        return False
