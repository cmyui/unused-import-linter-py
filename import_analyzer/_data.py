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


@dataclass
class IndirectImport:
    """An import that goes through a re-exporter instead of the source.

    Example (without alias):
        # core.py
        CONFIG = {}  # Original definition

        # utils/__init__.py
        from core import CONFIG  # Re-exports CONFIG

        # app.py (INDIRECT - this is what we detect)
        from utils import CONFIG  # Importing from re-exporter

        # app.py (DIRECT - what it should be)
        from core import CONFIG  # Importing from source

    Example (with alias):
        # core.py
        CONFIG = {}  # Original definition

        # utils/__init__.py
        from core import CONFIG as CONF  # Re-exports with alias

        # app.py (INDIRECT)
        from utils import CONF

        # app.py (DIRECT - preserves the alias)
        from core import CONFIG as CONF
    """

    file: Path  # File with the indirect import
    name: str  # Name as used in the importing file (e.g., "CONF")
    original_name: str  # Name as defined in original_source (e.g., "CONFIG")
    lineno: int  # Line number of the import
    current_source: Path  # Where it's imported from (re-exporter)
    original_source: Path  # Where it's actually defined
    is_same_package: bool  # True if re-exporter is __init__.py of original's package


def is_under_path(file_path: Path, base_path: Path) -> bool:
    """Check if a file is under the base path."""
    try:
        file_path.relative_to(base_path)
        return True
    except ValueError:
        return False
