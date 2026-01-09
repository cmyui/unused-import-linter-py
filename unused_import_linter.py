#!/usr/bin/env python3
"""
Unused Import Detector and Autofixer

A Python linter that detects unused imports and can automatically remove them.
"""

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImportInfo:
    """Information about an import statement."""

    name: str  # The name as it appears in code (alias if present, otherwise original)
    module: str  # The module being imported from (empty for 'import X')
    original_name: str  # The original name before aliasing
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int
    is_from_import: bool  # True for 'from X import Y', False for 'import X'
    full_node_lineno: int  # Line number of the full import statement
    full_node_end_lineno: int  # End line of the full import statement


class ImportExtractor(ast.NodeVisitor):
    """Extract all imports from an AST."""

    def __init__(self) -> None:
        self.imports: list[ImportInfo] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            # For 'import X.Y.Z', only 'X' is bound in the local namespace
            # For 'import X.Y.Z as W', 'W' is bound
            if alias.asname:
                name = alias.asname
            else:
                # Only the top-level name is bound
                name = alias.name.split(".")[0]

            self.imports.append(
                ImportInfo(
                    name=name,
                    module="",
                    original_name=alias.name,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or 0,
                    is_from_import=False,
                    full_node_lineno=node.lineno,
                    full_node_end_lineno=node.end_lineno or node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_FromImport(self, node: ast.ImportFrom) -> None:
        module = node.module or ""

        # Skip __future__ imports - they have side effects and are never "unused"
        if module == "__future__":
            return

        for alias in node.names:
            if alias.name == "*":
                # Star imports can't be analyzed for unused names
                continue

            name = alias.asname if alias.asname else alias.name
            self.imports.append(
                ImportInfo(
                    name=name,
                    module=module,
                    original_name=alias.name,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or 0,
                    is_from_import=True,
                    full_node_lineno=node.lineno,
                    full_node_end_lineno=node.end_lineno or node.lineno,
                )
            )
        self.generic_visit(node)

    # Alias for the actual AST node name
    visit_ImportFrom = visit_FromImport


class NameUsageCollector(ast.NodeVisitor):
    """Collect all name usages in the code, excluding import statements."""

    def __init__(self) -> None:
        self.used_names: set[str] = set()
        self._in_import = False

    def visit_Import(self, node: ast.Import) -> None:
        # Don't count names in import statements as usage
        pass

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Don't count names in import statements as usage
        pass

    def visit_Name(self, node: ast.Name) -> None:
        # Only count Load contexts as usages, not Store (assignment targets)
        # Store contexts: x = ..., for x in ..., with ... as x, except ... as x
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # For attribute access like 'os.path', we need to track 'os'
        # Only count Load contexts (reading), not Store (assignment targets)
        if not isinstance(node.ctx, ast.Load):
            self.generic_visit(node)
            return

        # Walk up to find the root name
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
            self.used_names.add(current.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Check decorators for name usage
        for decorator in node.decorator_list:
            self.visit(decorator)
        # Check annotations
        if node.returns:
            self.visit(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation:
                self.visit(arg.annotation)
        if node.args.vararg and node.args.vararg.annotation:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            self.visit(node.args.kwarg.annotation)
        # Visit body
        for child in node.body:
            self.visit(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Same logic as FunctionDef
        for decorator in node.decorator_list:
            self.visit(decorator)
        if node.returns:
            self.visit(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation:
                self.visit(arg.annotation)
        if node.args.vararg and node.args.vararg.annotation:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            self.visit(node.args.kwarg.annotation)
        for child in node.body:
            self.visit(child)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Check decorators and base classes
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        # Visit body
        for child in node.body:
            self.visit(child)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Handle annotated assignments: x: Type = value
        self.visit(node.annotation)
        if node.value:
            self.visit(node.value)
        if node.target:
            self.visit(node.target)


class StringAnnotationVisitor(ast.NodeVisitor):
    """Extract names from string annotations (forward references)."""

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            # Try to parse the string as a type annotation
            try:
                parsed = ast.parse(node.value, mode="eval")
                collector = NameUsageCollector()
                collector.visit(parsed)
                self.used_names.update(collector.used_names)
            except SyntaxError:
                pass
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # Handle things like Optional["ClassName"]
        self.visit(node.value)
        self.visit(node.slice)


def collect_string_annotation_names(tree: ast.AST) -> set[str]:
    """Collect names used in string annotations (forward references)."""
    visitor = StringAnnotationVisitor()
    visitor.visit(tree)
    return visitor.used_names


def collect_dunder_all_names(tree: ast.AST) -> set[str]:
    """Collect names exported via __all__.

    Names in __all__ are considered "used" because they're part of the public API.
    """
    names: set[str] = set()

    for node in ast.walk(tree):
        # Look for __all__ = [...] or __all__ += [...]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    names.update(_extract_string_list(node.value))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                names.update(_extract_string_list(node.value))

    return names


def _extract_string_list(node: ast.expr) -> set[str]:
    """Extract string values from a list/tuple literal."""
    names: set[str] = set()

    if isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.add(elt.value)

    return names


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

    # Collect used names
    usage_collector = NameUsageCollector()
    usage_collector.visit(tree)

    # Also check string annotations
    string_names = collect_string_annotation_names(tree)

    # Also check __all__ exports (names in __all__ are considered used)
    dunder_all_names = collect_dunder_all_names(tree)

    all_used_names = usage_collector.used_names | string_names | dunder_all_names

    # Find unused imports
    unused: list[ImportInfo] = []
    for imp in import_extractor.imports:
        if imp.name not in all_used_names:
            unused.append(imp)

    return unused


def _find_block_only_imports(
    tree: ast.AST, unused_import_lines: set[int]
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
        # Find all imports in this body
        import_stmts = [
            stmt for stmt in body if isinstance(stmt, (ast.Import, ast.ImportFrom))
        ]
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
            if hasattr(node, "body") and node.body:
                check_body(node.body)
            if hasattr(node, "orelse") and node.orelse:
                check_body(node.orelse)
            if hasattr(node, "finalbody") and node.finalbody:
                check_body(node.finalbody)
            if hasattr(node, "handlers"):
                for handler in node.handlers:
                    if handler.body:
                        check_body(handler.body)

    return needs_pass


def remove_unused_imports(source: str, unused_imports: list[ImportInfo]) -> str:
    """Remove unused imports from the source code."""
    if not unused_imports:
        return source

    lines = source.splitlines(keepends=True)

    # Group unused imports by their statement line
    # For multi-name imports like 'from X import a, b, c', we may only remove some names
    imports_by_line: dict[int, list[ImportInfo]] = {}

    for imp in unused_imports:
        line_idx = imp.full_node_lineno - 1
        if line_idx not in imports_by_line:
            imports_by_line[line_idx] = []
        imports_by_line[line_idx].append(imp)

    # Parse again to get all imports on each line
    tree = ast.parse(source)
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
    lines_to_modify: dict[int, tuple[ast.AST, list[str]]] = {}

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
                        for i in range(node.lineno - 1, (node.end_lineno or node.lineno)):
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
                new_line = f"{indent_str}from {level}{module} import {', '.join(parts)}\n"

            new_lines.append(new_line)
            # Skip any continuation lines
            end_line = node.end_lineno or node.lineno
            i = end_line
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


def check_file(filepath: Path, fix: bool = False) -> tuple[int, list[str]]:
    """Check a file for unused imports.

    Returns:
        Tuple of (number of unused imports found, list of messages)
    """
    messages: list[str] = []

    try:
        source = filepath.read_text()
    except (OSError, UnicodeDecodeError) as e:
        messages.append(f"Error reading {filepath}: {e}")
        return 0, messages

    unused = find_unused_imports(source)

    if not unused:
        return 0, messages

    for imp in unused:
        if imp.is_from_import:
            msg = f"{filepath}:{imp.lineno}: Unused import '{imp.name}' from '{imp.module}'"
        else:
            msg = f"{filepath}:{imp.lineno}: Unused import '{imp.name}'"
        messages.append(msg)

    if fix:
        new_source = remove_unused_imports(source, unused)
        if new_source != source:
            filepath.write_text(new_source)
            messages.append(f"Fixed {len(unused)} unused import(s) in {filepath}")

    return len(unused), messages


def collect_python_files(paths: list[Path]) -> list[Path]:
    """Collect all Python files from given paths."""
    files: list[Path] = []

    for path in paths:
        if path.is_file():
            if path.suffix == ".py":
                files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.py"))

    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect and optionally fix unused Python imports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s myfile.py              Check a single file
  %(prog)s src/                   Check all .py files in a directory
  %(prog)s --fix myfile.py        Fix unused imports in place
  %(prog)s --fix src/             Fix all files in a directory
        """,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files or directories to check",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically remove unused imports",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show summary, not individual issues",
    )

    args = parser.parse_args()

    files = collect_python_files(args.paths)

    if not files:
        print("No Python files found", file=sys.stderr)
        return 1

    total_unused = 0
    total_files_with_issues = 0

    for filepath in files:
        count, messages = check_file(filepath, fix=args.fix)
        if count > 0:
            total_unused += count
            total_files_with_issues += 1
            if not args.quiet:
                for msg in messages:
                    print(msg)

    if total_unused > 0:
        action = "Fixed" if args.fix else "Found"
        print(
            f"\n{action} {total_unused} unused import(s) in {total_files_with_issues} file(s)"
        )
        return 0 if args.fix else 1
    else:
        print("No unused imports found")
        return 0


if __name__ == "__main__":
    sys.exit(main())
