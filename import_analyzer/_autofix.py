from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from import_analyzer._data import ImportInfo
from import_analyzer._data import IndirectImport


def _find_block_only_imports(
    tree: ast.AST,
    unused_import_lines: set[int],
) -> dict[int, bool]:
    """Find imports that, when removed, would leave their block empty.

    Returns a dict mapping line numbers to True if removing that import
    (along with other unused imports) would leave the block empty.
    The first import in such a block should be replaced with 'pass'.
    """
    needs_pass: dict[int, bool] = {}

    # Node types that have a 'body' attribute containing statements
    block_parents = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.If,
        ast.With,
        ast.AsyncWith,
        ast.Try,
        ast.ExceptHandler,
    )

    def check_body(body: list[ast.stmt]) -> None:
        """Check if removing unused imports would leave this block empty."""
        # Check if all statements are imports that will be removed
        all_are_unused_imports = all(
            isinstance(stmt, (ast.Import, ast.ImportFrom))
            and (stmt.lineno - 1) in unused_import_lines
            for stmt in body
        )
        if all_are_unused_imports and body:
            # Mark the first import line to be replaced with pass
            needs_pass[body[0].lineno - 1] = True

    for node in ast.walk(tree):
        if isinstance(node, block_parents):
            # All block_parents have 'body'
            if node.body:
                check_body(node.body)

        # Check 'orelse' for nodes that have it
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.Try)):
            if node.orelse:
                check_body(node.orelse)

        # Check 'finalbody' and 'handlers' for Try
        if isinstance(node, ast.Try):
            if node.finalbody:
                check_body(node.finalbody)
            for handler in node.handlers:
                if handler.body:
                    check_body(handler.body)

    return needs_pass


def _get_import_names(node: ast.Import | ast.ImportFrom) -> set[str]:
    """Get all bound names from an import node."""
    names: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.add(alias.asname or alias.name.split(".")[0])
    else:  # ImportFrom
        for alias in node.names:
            if alias.name != "*":
                names.add(alias.asname or alias.name)
    return names


def _find_semicolon_removals(
    tree: ast.AST,
    source: str,
    unused_names: set[str],
) -> tuple[dict[int, list[tuple[int, int]]], set[int]]:
    """Find surgical removal ranges for imports on semicolon lines.

    Returns:
        - dict mapping line index to list of (start_col, end_col) ranges
          to remove from that line
        - set of line indices that should be completely removed (preceding
          lines of multiline imports that end on semicolon lines)
    """
    lines = source.splitlines(keepends=True)
    removals: dict[int, list[tuple[int, int]]] = {}
    lines_to_remove: set[int] = set()

    # Group all statements by the line where they end
    # For multiline statements ending on semicolon lines, use the END line
    # But filter to only include statements that could be semicolon-separated
    # (statements with content on the same physical line)
    stmts_by_line: dict[int, list[ast.stmt]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
            end_lineno = node.end_lineno or node.lineno
            # For compound statements (if, for, etc.), skip them as they
            # contain other statements rather than being semicolon-separated
            if isinstance(
                node,
                (
                    ast.If,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.With,
                    ast.AsyncWith,
                    ast.Try,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Match,
                ),
            ):
                continue
            line_idx = end_lineno - 1
            if line_idx not in stmts_by_line:
                stmts_by_line[line_idx] = []
            stmts_by_line[line_idx].append(node)

    # Sort statements by their position on the shared line
    # For multiline statements, use end_col_offset; for single-line, use col_offset
    def sort_key(n: ast.stmt) -> int:
        if n.end_lineno and n.end_lineno != n.lineno:
            # Multiline statement - sort by where it ends
            return n.end_col_offset or 0
        return n.col_offset

    for stmts in stmts_by_line.values():
        stmts.sort(key=sort_key)

    for line_idx, stmts in stmts_by_line.items():
        if len(stmts) <= 1:
            continue

        line = lines[line_idx] if line_idx < len(lines) else ""
        line_removals: list[tuple[int, int]] = []

        for i, stmt in enumerate(stmts):
            if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                continue

            # Check if ALL names in this import are unused
            import_names = _get_import_names(stmt)
            if not import_names.issubset(unused_names):
                continue

            # This import should be removed - calculate the range
            start_col = stmt.col_offset
            end_col = stmt.end_col_offset or len(line.rstrip("\n"))

            # Determine if we need to include semicolon before or after
            # Handle any whitespace (spaces, tabs) around semicolons
            if i == 0:
                # First statement - remove trailing whitespace, semicolon, whitespace
                rest = line[end_col:]
                # Strip: optional whitespace, semicolon, optional whitespace
                stripped = rest.lstrip(" \t")
                if stripped.startswith(";"):
                    stripped = stripped[1:].lstrip(" \t")
                # Calculate how much extra to remove
                end_col += len(rest) - len(stripped)
            else:
                # Not first - remove leading whitespace, semicolon, whitespace
                prefix = line[:start_col]
                # Strip from right: optional whitespace, semicolon, optional whitespace
                stripped = prefix.rstrip(" \t")
                if stripped.endswith(";"):
                    stripped = stripped[:-1].rstrip(" \t")
                # Calculate new start position
                start_col = len(stripped)

            line_removals.append((start_col, end_col))

            # For multiline imports, also mark preceding lines for removal
            if stmt.lineno != stmt.end_lineno:
                for remove_line in range(
                    stmt.lineno - 1, (stmt.end_lineno or stmt.lineno) - 1,
                ):
                    lines_to_remove.add(remove_line)

        if line_removals:
            removals[line_idx] = line_removals

    return removals, lines_to_remove


def remove_unused_imports(source: str, unused_imports: list[ImportInfo]) -> str:
    """Remove unused imports from the source code."""
    if not unused_imports:
        return source

    lines = source.splitlines(keepends=True)

    # Parse to analyze the source
    tree = ast.parse(source)

    unused_names = {imp.name for imp in unused_imports}

    # Find surgical removals for semicolon lines
    semicolon_removals, semicolon_lines_to_remove = _find_semicolon_removals(
        tree,
        source,
        unused_names,
    )

    # Group unused imports by their statement line
    # For multi-name imports like 'from X import a, b, c', we may only remove some
    imports_by_line: dict[int, list[ImportInfo]] = {}

    for imp in unused_imports:
        line_idx = imp.full_node_lineno - 1
        # Skip imports that will be handled by semicolon removal
        # Check both start and end line (for multiline imports)
        end_line_idx = (imp.end_lineno or imp.lineno) - 1
        if line_idx in semicolon_removals or end_line_idx in semicolon_removals:
            continue
        if line_idx not in imports_by_line:
            imports_by_line[line_idx] = []
        imports_by_line[line_idx].append(imp)

    all_imports_by_line: dict[int, list[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            line_idx = node.lineno - 1
            names = [
                alias.asname if alias.asname else alias.name.split(".")[0]
                for alias in node.names
            ]
            all_imports_by_line[line_idx] = names
        elif isinstance(node, ast.ImportFrom):
            line_idx = node.lineno - 1
            names = [
                alias.asname if alias.asname else alias.name
                for alias in node.names
                if alias.name != "*"
            ]
            all_imports_by_line[line_idx] = names

    # First pass: identify all lines that will be completely removed
    lines_to_fully_remove: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            line_idx = node.lineno - 1
            if line_idx in imports_by_line:
                unused_names = {imp.name for imp in imports_by_line[line_idx]}
                all_names = set(all_imports_by_line.get(line_idx, []))
                if unused_names >= all_names:
                    lines_to_fully_remove.add(line_idx)

    # Find which imports need to be replaced with 'pass' to avoid empty blocks
    needs_pass = _find_block_only_imports(tree, lines_to_fully_remove)

    # Determine which lines to remove entirely, modify, or replace with pass
    lines_to_remove: set[int] = set(semicolon_lines_to_remove)
    lines_to_pass: set[int] = set()  # Replace with 'pass' instead of removing
    lines_to_modify: dict[int, tuple[ast.Import | ast.ImportFrom, list[str]]] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            line_idx = node.lineno - 1
            if line_idx in imports_by_line:
                unused_names = {imp.name for imp in imports_by_line[line_idx]}
                all_names = set(all_imports_by_line.get(line_idx, []))

                if unused_names >= all_names:
                    # All imports on this line are unused
                    if line_idx in needs_pass:
                        # This removal would leave a block empty, replace with pass
                        lines_to_pass.add(line_idx)
                        for i in range(node.lineno, (node.end_lineno or node.lineno)):
                            lines_to_remove.add(i)
                    else:
                        # Remove the whole line(s)
                        for i in range(
                            node.lineno - 1,
                            (node.end_lineno or node.lineno),
                        ):
                            lines_to_remove.add(i)
                else:
                    # Only some imports are unused, need to modify the line
                    remaining = [n for n in all_names if n not in unused_names]
                    lines_to_modify[line_idx] = (node, remaining)

    # Build new source
    new_lines: list[str] = []
    i = 0
    while i < len(lines):
        if i in lines_to_pass:
            # Replace import with pass, preserving indentation
            original_line = lines[i]
            indent = len(original_line) - len(original_line.lstrip())
            new_lines.append(" " * indent + "pass\n")
            # Skip any continuation lines of this import
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if node.lineno - 1 == i:
                        end_line = node.end_lineno or node.lineno
                        i = end_line
                        break
            else:
                i += 1
        elif i in lines_to_remove:
            # Skip this line (and find the end of multi-line imports)
            # But don't skip past lines that need surgical removal
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if node.lineno - 1 == i:
                        end_line = node.end_lineno or node.lineno
                        # Don't skip past semicolon removal lines
                        end_line_idx = end_line - 1
                        if end_line_idx in semicolon_removals:
                            # Stop before the semicolon line
                            i = end_line_idx
                        else:
                            i = end_line
                        break
            else:
                i += 1
        elif i in lines_to_modify:
            node, remaining = lines_to_modify[i]
            # Get original indentation
            original_line = lines[i]
            indent = len(original_line) - len(original_line.lstrip())
            indent_str = " " * indent

            # Reconstruct the import line
            if isinstance(node, ast.Import):
                alias_map = {}
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split(".")[0]
                    if alias.asname:
                        alias_map[name] = f"{alias.name} as {alias.asname}"
                    else:
                        alias_map[name] = alias.name
                parts = [alias_map[n] for n in remaining if n in alias_map]
                new_line = f"{indent_str}import {', '.join(parts)}\n"
            else:  # ImportFrom
                alias_map = {}
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    if alias.asname:
                        alias_map[name] = f"{alias.name} as {alias.asname}"
                    else:
                        alias_map[name] = alias.name
                parts = [alias_map[n] for n in remaining if n in alias_map]
                module = node.module or ""
                level = "." * node.level
                new_line = (
                    f"{indent_str}from {level}{module} import {', '.join(parts)}\n"
                )

            new_lines.append(new_line)
            # Skip any continuation lines
            end_line = node.end_lineno or node.lineno
            i = end_line
        elif i in semicolon_removals:
            # Apply surgical removals to this line
            line = lines[i]
            # Apply removals in reverse order to preserve column offsets
            for start_col, end_col in reversed(semicolon_removals[i]):
                line = line[:start_col] + line[end_col:]
            # Only add the line if there's content left after removals
            stripped = line.strip()
            if stripped and stripped != "\n":
                new_lines.append(line)
            i += 1
        else:
            new_lines.append(lines[i])
            i += 1

    # Remove trailing blank lines that might result from removed imports
    result = "".join(new_lines)

    # Clean up dangling backslash continuations
    # If a line ends with "\" but the next line was removed, remove the backslash
    result_lines = result.splitlines(keepends=True)
    cleaned_backslash: list[str] = []
    for idx, line in enumerate(result_lines):
        # Check if this line ends with backslash continuation
        line_content = line.rstrip("\n\r")
        if line_content.rstrip(" \t").endswith("\\"):
            # Check if next line exists and has content (not just whitespace)
            next_idx = idx + 1
            if next_idx >= len(result_lines) or not result_lines[next_idx].strip():
                # Remove the trailing backslash and whitespace/semicolon before it
                stripped = line_content.rstrip(" \t")[:-1].rstrip(" \t;")
                if stripped:
                    cleaned_backslash.append(stripped + "\n")
                # else: line becomes empty, skip it
                continue
        cleaned_backslash.append(line)

    result = "".join(cleaned_backslash)

    # Fix leading whitespace on first non-blank line if it would cause invalid syntax
    # This can happen when removing imports that had backslash continuations
    result_lines = result.splitlines(keepends=True)
    if result_lines:
        first_content_idx = 0
        for idx, line in enumerate(result_lines):
            if line.strip():
                first_content_idx = idx
                break
        first_line = result_lines[first_content_idx]
        if first_line and first_line[0] in " \t":
            # First content line has leading whitespace - strip it
            result_lines[first_content_idx] = first_line.lstrip()
        result = "".join(result_lines)

    # Clean up multiple consecutive blank lines at the top
    result_lines = result.splitlines(keepends=True)
    cleaned_lines: list[str] = []
    seen_code = False
    blank_count = 0

    for line in result_lines:
        if line.strip() == "":
            if seen_code:
                cleaned_lines.append(line)
            else:
                blank_count += 1
                if blank_count <= 1:
                    cleaned_lines.append(line)
        else:
            seen_code = True
            blank_count = 0
            cleaned_lines.append(line)

    return "".join(cleaned_lines)


@dataclass
class _IndirectInfo:
    """Info about an indirect import for fixing."""

    module: str  # Target module name
    original_name: str  # Name in the original source
    local_name: str  # Name as used locally (may differ due to aliases)


def fix_indirect_imports(
    source: str,
    indirect_imports: list[IndirectImport],
    module_names: dict[Path, str],
) -> str:
    """Rewrite indirect imports to use direct sources.

    Args:
        source: The source code to modify
        indirect_imports: List of indirect imports to fix
        module_names: Mapping from file paths to module names

    Returns:
        Modified source code with indirect imports replaced

    Example:
        If we have:
            # logger.py: LOGGER = ...
            # models/__init__.py: from logger import LOGGER as LOG
            # app.py: from models import LOG

        The fix will produce:
            # app.py: from logger import LOGGER as LOG

        This preserves the local name (LOG) while importing from the source.
    """
    if not indirect_imports:
        return source

    # Build lookup: (lineno, local_name) -> _IndirectInfo
    indirect_by_line: dict[int, dict[str, _IndirectInfo]] = defaultdict(dict)
    for ind in indirect_imports:
        module_name = module_names.get(ind.original_source)
        if module_name:
            indirect_by_line[ind.lineno][ind.name] = _IndirectInfo(
                module=module_name,
                original_name=ind.original_name,
                local_name=ind.name,
            )

    if not indirect_by_line:
        return source

    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    # Find ImportFrom nodes that need modification
    modifications: list[tuple[int, int, str]] = []  # (start_line, end_line, new_code)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue

        line_idx = node.lineno
        if line_idx not in indirect_by_line:
            continue

        indirect_lookup = indirect_by_line[line_idx]

        # Get all aliases in this import
        aliases = [(alias.name, alias.asname) for alias in node.names]

        # Separate into indirect and direct imports
        # Group indirect imports by their target module
        indirect_by_module: dict[str, list[_IndirectInfo]] = defaultdict(list)
        direct_imports: list[tuple[str, str | None]] = []

        for name, asname in aliases:
            local_name = asname or name
            if local_name in indirect_lookup:
                info = indirect_lookup[local_name]
                indirect_by_module[info.module].append(info)
            else:
                direct_imports.append((name, asname))

        if not indirect_by_module:
            continue

        # Get original indentation
        original_line = lines[node.lineno - 1]
        indent = len(original_line) - len(original_line.lstrip())
        indent_str = " " * indent

        # Build new import lines
        new_imports: list[str] = []

        # Keep direct imports from original module (if any)
        if direct_imports:
            parts = []
            for name, asname in direct_imports:
                if asname:
                    parts.append(f"{name} as {asname}")
                else:
                    parts.append(name)
            module = node.module or ""
            level = "." * node.level
            new_imports.append(
                f"{indent_str}from {level}{module} import {', '.join(parts)}",
            )

        # Add new imports from original sources
        for module, infos in sorted(indirect_by_module.items()):
            parts = []
            for info in infos:
                if info.original_name != info.local_name:
                    # Need alias: from X import ORIGINAL as LOCAL
                    parts.append(f"{info.original_name} as {info.local_name}")
                else:
                    parts.append(info.original_name)
            new_imports.append(f"{indent_str}from {module} import {', '.join(parts)}")

        new_code = "\n".join(new_imports)
        end_line = node.end_lineno or node.lineno
        modifications.append((node.lineno - 1, end_line - 1, new_code))

    if not modifications:
        return source

    # Apply modifications in reverse order to preserve line numbers
    modifications.sort(key=lambda x: x[0], reverse=True)

    for start_line, end_line, new_code in modifications:
        # Replace lines from start_line to end_line (inclusive) with new_code
        before = lines[:start_line]
        after = lines[end_line + 1:]
        lines = before + [new_code + "\n"] + after

    return "".join(lines)
