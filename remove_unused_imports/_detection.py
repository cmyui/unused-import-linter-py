from __future__ import annotations

import ast
import sys

from remove_unused_imports._ast_helpers import ImportExtractor
from remove_unused_imports._ast_helpers import ScopeAwareNameCollector
from remove_unused_imports._ast_helpers import collect_dunder_all_names
from remove_unused_imports._ast_helpers import collect_string_annotation_names
from remove_unused_imports._data import ImportInfo


def find_unused_imports(source: str) -> list[ImportInfo]:
    """Find all unused imports in the given source code."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"Syntax error: {e}", file=sys.stderr)
        return []

    # Extract imports
    import_extractor = ImportExtractor()
    import_extractor.visit(tree)

    # Collect used names with scope analysis
    usage_collector = ScopeAwareNameCollector()
    usage_collector.visit(tree)

    # Also check string annotations
    string_names = collect_string_annotation_names(tree)

    # Also check __all__ exports (names in __all__ are considered used)
    dunder_all_names = collect_dunder_all_names(tree)

    all_used_names = (
        usage_collector.module_scope_usages | string_names | dunder_all_names
    )

    # Find unused imports
    unused: list[ImportInfo] = []
    for imp in import_extractor.imports:
        if imp.name not in all_used_names:
            unused.append(imp)

    return unused
