from __future__ import annotations

import ast

from remove_unused_imports._data import ImportInfo


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
) -> dict[int, list[tuple[int, int]]]:
    """Find surgical removal ranges for imports on semicolon lines.

    Returns dict mapping line index to list of (start_col, end_col) ranges
    to remove from that line.
    """
    lines = source.splitlines(keepends=True)
    removals: dict[int, list[tuple[int, int]]] = {}

    # Group all statements by line number, sorted by column
    stmts_by_line: dict[int, list[ast.stmt]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and hasattr(node, 'lineno'):
            line_idx = node.lineno - 1
            if line_idx not in stmts_by_line:
                stmts_by_line[line_idx] = []
            stmts_by_line[line_idx].append(node)

    # Sort statements by column offset
    for stmts in stmts_by_line.values():
        stmts.sort(key=lambda n: n.col_offset)

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
            end_col = stmt.end_col_offset or len(line.rstrip('\n'))

            # Determine if we need to include semicolon before or after
            if i == 0:
                # First statement - remove trailing "; "
                # Find the semicolon after end_col
                rest = line[end_col:]
                semi_match = len(rest) - len(rest.lstrip('; '))
                end_col += semi_match
            else:
                # Not first - remove leading "; "
                # Find semicolon before start_col
                prefix = line[:start_col]
                semi_match = len(prefix) - len(prefix.rstrip('; '))
                start_col -= semi_match

            line_removals.append((start_col, end_col))

        if line_removals:
            removals[line_idx] = line_removals

    return removals


def remove_unused_imports(source: str, unused_imports: list[ImportInfo]) -> str:
    """Remove unused imports from the source code."""
    if not unused_imports:
        return source

    lines = source.splitlines(keepends=True)

    # Parse to analyze the source
    tree = ast.parse(source)

    unused_names = {imp.name for imp in unused_imports}

    # Find surgical removals for semicolon lines
    semicolon_removals = _find_semicolon_removals(tree, source, unused_names)

    # Group unused imports by their statement line
    # For multi-name imports like 'from X import a, b, c', we may only remove some
    imports_by_line: dict[int, list[ImportInfo]] = {}

    for imp in unused_imports:
        line_idx = imp.full_node_lineno - 1
        # Skip imports that will be handled by semicolon removal
        if line_idx in semicolon_removals:
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
    lines_to_remove: set[int] = set()
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
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if node.lineno - 1 == i:
                        end_line = node.end_lineno or node.lineno
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
