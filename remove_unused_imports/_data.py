from __future__ import annotations

from dataclasses import dataclass


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
