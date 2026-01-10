from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from import_analyzer._autofix import fix_indirect_imports
from import_analyzer._autofix import remove_unused_imports
from import_analyzer._cross_file import analyze_cross_file
from import_analyzer._data import ImportInfo
from import_analyzer._data import IndirectImport
from import_analyzer._data import is_under_path
from import_analyzer._detection import find_unused_imports
from import_analyzer._format import format_cross_file_results
from import_analyzer._graph import ImportGraph
from import_analyzer._graph import build_import_graph
from import_analyzer._graph import build_import_graph_from_directory


def check_file(filepath: Path, fix_unused: bool = False) -> tuple[int, list[str]]:
    """Check a file for unused imports (single-file mode).

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

    if fix_unused:
        new_source = remove_unused_imports(source, unused)
        if new_source != source:
            filepath.write_text(new_source)
            messages.append(
                f"Fixed {len(unused)} unused import(s) in {filepath}",
            )

    return len(unused), messages


def check_cross_file(
    path: Path,
    fix_unused: bool = False,
    fix_indirect: bool = False,
    warn_implicit_reexports: bool = False,
    warn_circular: bool = False,
    warn_unreachable: bool = False,
    strict_indirect_imports: bool = False,
    quiet: bool = False,
) -> tuple[int, list[str]]:
    """Check imports across files (cross-file mode).

    Args:
        path: Entry point file or directory to analyze
        fix_unused: Whether to fix unused imports
        fix_indirect: Whether to fix indirect imports (rewrite to direct sources)
        warn_implicit_reexports: Whether to warn about implicit re-exports
        warn_circular: Whether to warn about circular imports
        warn_unreachable: Whether to warn about unreachable files
        strict_indirect_imports: Also flag same-package __init__.py re-exports
        quiet: Whether to suppress individual issue messages

    Returns:
        Tuple of (number of issues found, list of messages)
    """
    # Build import graph
    entry_point: Path | None = None
    if path.is_file():
        graph = build_import_graph(path)
        entry_point = path.resolve()
    else:
        graph = build_import_graph_from_directory(path)
        # No single entry point for directory mode

    # Analyze (pass entry point for file reachability tracking)
    result = analyze_cross_file(
        graph,
        entry_point,
        include_same_package_indirect=strict_indirect_imports,
    )

    # Fix indirect imports first (if requested)
    # This enables cascade: after fixing indirect imports, the re-exports become unused
    indirect_fixed_files: dict[Path, int] = {}
    if fix_indirect and result.indirect_imports:
        indirect_fixed_files = _fix_indirect_imports(
            result.indirect_imports,
            graph,
            path,
        )

    # Filter results to only files under the target path
    # (graph may include files discovered via imports outside the target directory)
    target_path = path.parent if path.is_file() else path
    target_path = target_path.resolve()

    filtered_unused = {
        fp: unused
        for fp, unused in result.unused_imports.items()
        if is_under_path(fp, target_path)
    }

    # Count total issues (from filtered results)
    total_issues = sum(len(unused) for unused in filtered_unused.values())

    # Fix files if requested (only files under target path)
    fixed_files: dict[Path, int] = {}
    if fix_unused:
        for file_path, unused in filtered_unused.items():
            count = _fix_file_silent(file_path, unused)
            if count > 0:
                fixed_files[file_path] = count

    # Format results using the new formatter
    messages = format_cross_file_results(
        result=result,
        base_path=path,
        fix_unused=fix_unused,
        warn_implicit_reexports=warn_implicit_reexports,
        warn_circular=warn_circular,
        warn_unreachable=warn_unreachable,
        quiet=quiet,
        fixed_files=fixed_files,
    )

    # Add indirect fix summary if we fixed any
    if indirect_fixed_files:
        total_indirect = sum(indirect_fixed_files.values())
        messages.insert(
            0,
            f"Fixed {total_indirect} indirect import(s) in {len(indirect_fixed_files)} file(s)",
        )
        messages.insert(1, "")

    return total_issues, messages


def _fix_file_silent(
    file_path: Path,
    unused: list[ImportInfo],
) -> int:
    """Fix unused imports in a file.

    Returns:
        Number of imports fixed (0 if file couldn't be read/written)
    """
    try:
        source = file_path.read_text()
    except (OSError, UnicodeDecodeError):
        return 0

    new_source = remove_unused_imports(source, unused)
    if new_source != source:
        file_path.write_text(new_source)
        return len(unused)
    return 0


def _fix_indirect_imports(
    indirect_imports: list[IndirectImport],
    graph: ImportGraph,
    base_path: Path,
) -> dict[Path, int]:
    """Fix indirect imports by rewriting them to use direct sources.

    Args:
        indirect_imports: List of indirect imports to fix
        graph: The import graph (for module name lookup)
        base_path: Base path for filtering (only fix files under this path)

    Returns:
        Dict mapping file paths to number of imports fixed
    """

    # Filter to only files under base_path
    if base_path.is_file():
        base_path = base_path.parent
    base_path = base_path.resolve()

    filtered_indirect = [
        ind for ind in indirect_imports if is_under_path(ind.file, base_path)
    ]

    if not filtered_indirect:
        return {}

    # Build module name lookup from graph
    module_names: dict[Path, str] = {}
    for file_path, module_info in graph.nodes.items():
        module_names[file_path] = module_info.module_name

    # Group indirect imports by file
    by_file: dict[Path, list[IndirectImport]] = defaultdict(list)
    for ind in filtered_indirect:
        by_file[ind.file].append(ind)

    # Fix each file
    fixed_files: dict[Path, int] = {}
    for file_path, file_indirect in by_file.items():
        try:
            source = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        new_source = fix_indirect_imports(source, file_indirect, module_names)
        if new_source != source:
            file_path.write_text(new_source)
            fixed_files[file_path] = len(file_indirect)

    return fixed_files


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
  %(prog)s main.py                   Cross-file analysis from entry point
  %(prog)s src/                      Cross-file analysis of directory
  %(prog)s --fix-unused-imports main.py       Fix unused imports
  %(prog)s --fix-indirect-imports main.py     Fix indirect imports
  %(prog)s --warn-implicit-reexports main.py
  %(prog)s --warn-circular main.py
  %(prog)s --warn-unreachable main.py
  %(prog)s --single-file myfile.py   Single-file mode (no cross-file tracking)
        """,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files or directories to check",
    )
    parser.add_argument(
        "--fix-unused-imports",
        action="store_true",
        dest="fix_unused",
        help="Automatically remove unused imports",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show summary, not individual issues",
    )
    parser.add_argument(
        "--single-file",
        action="store_true",
        help="Use single-file mode (no cross-file import tracking)",
    )
    parser.add_argument(
        "--warn-implicit-reexports",
        action="store_true",
        help="Warn when imports are re-exported without being in __all__",
    )
    parser.add_argument(
        "--warn-circular",
        action="store_true",
        help="Warn about circular import chains",
    )
    parser.add_argument(
        "--warn-unreachable",
        action="store_true",
        help="Warn about files that become unreachable after fixing imports",
    )
    parser.add_argument(
        "--strict-indirect-imports",
        action="store_true",
        help="Also flag same-package __init__.py re-exports (use with --fix-indirect-imports)",
    )
    parser.add_argument(
        "--fix-indirect-imports",
        action="store_true",
        dest="fix_indirect",
        help="Rewrite indirect imports to use direct sources",
    )

    args = parser.parse_args()

    # Determine mode
    if args.single_file:
        return _main_single_file(args)
    else:
        return _main_cross_file(args)


def _main_single_file(args: argparse.Namespace) -> int:
    """Run in single-file mode (original behavior)."""
    files = collect_python_files(args.paths)

    if not files:
        print("No Python files found", file=sys.stderr)
        return 1

    total_unused = 0
    total_files_with_issues = 0

    for filepath in files:
        count, messages = check_file(filepath, fix_unused=args.fix_unused)
        if count > 0:
            total_unused += count
            total_files_with_issues += 1
            if not args.quiet:
                for msg in messages:
                    print(msg)

    if total_unused > 0:
        action = "Fixed" if args.fix_unused else "Found"
        print(
            f"\n{action} {total_unused} unused import(s) "
            f"in {total_files_with_issues} file(s)",
        )
        return 0 if args.fix_unused else 1
    else:
        print("No unused imports found")
        return 0


def _main_cross_file(args: argparse.Namespace) -> int:
    """Run in cross-file mode (default)."""
    # In cross-file mode, we expect either a single entry point file
    # or a single directory
    if len(args.paths) > 1:
        print(
            "Cross-file mode expects a single entry point file or directory. "
            "Use --single-file for multiple paths.",
            file=sys.stderr,
        )
        return 1

    path = args.paths[0]

    if not path.exists():
        print(f"Path not found: {path}", file=sys.stderr)
        return 1

    total_issues, messages = check_cross_file(
        path,
        fix_unused=args.fix_unused,
        fix_indirect=args.fix_indirect,
        warn_implicit_reexports=args.warn_implicit_reexports,
        warn_circular=args.warn_circular,
        warn_unreachable=args.warn_unreachable,
        strict_indirect_imports=args.strict_indirect_imports,
        quiet=args.quiet,
    )

    # The formatter already includes the summary, so just print all messages
    for msg in messages:
        print(msg)

    # Return code: 0 if no issues or fixed, 1 if issues found and not fixed
    if total_issues > 0 and not args.fix_unused:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
