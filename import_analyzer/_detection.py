from __future__ import annotations

import ast
import re
import sys

from import_analyzer._ast_helpers import ImportExtractor
from import_analyzer._ast_helpers import ScopeAwareNameCollector
from import_analyzer._ast_helpers import collect_dunder_all_names
from import_analyzer._ast_helpers import collect_string_annotation_names
from import_analyzer._ast_helpers import collect_type_comment_names
from import_analyzer._data import ImportInfo

# Pattern to match noqa comments: # noqa or # noqa: F401 or # noqa: F401, E501
# The "noqa" keyword is case-insensitive, but codes are case-sensitive (matching flake8)
# The codes group captures only alphanumeric codes separated by commas/spaces
_NOQA_PATTERN = re.compile(
    r"#\s*noqa(?:\s*:\s*([A-Za-z0-9]+(?:\s*,\s*[A-Za-z0-9]+)*))?",
    re.IGNORECASE,
)


def _has_noqa_f401(line: str) -> bool:
    """Check if a line has a noqa comment that suppresses F401 (unused import)."""
    match = _NOQA_PATTERN.search(line)
    if not match:
        return False

    # If no specific codes given (just "# noqa"), it suppresses everything
    codes = match.group(1)
    if codes is None:
        return True

    # Check if F401 is in the list of suppressed codes
    # Codes are case-sensitive to match flake8 behavior
    suppressed = {code.strip() for code in codes.split(",")}
    return "F401" in suppressed


def _check_continuation_noqa(lines: list[str], start_lineno: int) -> bool:
    """Check if there's a noqa comment on continuation lines after start_lineno.

    This handles backslash continuation where noqa might be on a following line:
        import os \\
        # noqa: F401

    Args:
        lines: Source code lines (0-indexed)
        start_lineno: 1-indexed line number to start checking from
    """
    # Start from the line with the import name (0-indexed)
    idx = start_lineno - 1
    if idx >= len(lines):
        return False

    # Follow backslash continuations
    while idx < len(lines) and lines[idx].rstrip().endswith("\\"):
        idx += 1
        if idx < len(lines) and _has_noqa_f401(lines[idx]):
            return True

    return False


def find_unused_imports(source: str, ignore_all: bool = False) -> list[ImportInfo]:
    """Find all unused imports in the given source code.

    Args:
        source: Python source code to analyze
        ignore_all: If True, don't consider __all__ as usage. Used by cross-file
            analysis to identify imports that exist solely for re-export.
    """
    try:
        tree = ast.parse(source, type_comments=True)
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

    # Also check type comments (PEP 484 style)
    type_comment_names = collect_type_comment_names(tree)

    # Also check __all__ exports (names in __all__ are considered used)
    # Unless ignore_all is True (for cross-file analysis)
    if ignore_all:
        dunder_all_names: set[str] = set()
    else:
        dunder_all_names = collect_dunder_all_names(tree)

    all_used_names = (
        usage_collector.module_scope_usages
        | string_names
        | type_comment_names
        | dunder_all_names
    )

    # Split source into lines for noqa checking
    lines = source.splitlines()

    # Find unused imports
    unused: list[ImportInfo] = []
    for imp in import_extractor.imports:
        if imp.name not in all_used_names:
            # Check if the import has a noqa comment suppressing F401
            # First check the specific alias line
            line_idx = imp.lineno - 1
            if line_idx < len(lines) and _has_noqa_f401(lines[line_idx]):
                continue
            # Then check for backslash continuation lines
            if _check_continuation_noqa(lines, imp.lineno):
                continue
            unused.append(imp)

    return unused
