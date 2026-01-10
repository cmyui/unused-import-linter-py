from __future__ import annotations

import argparse
import sys
from pathlib import Path

from remove_unused_imports._autofix import remove_unused_imports
from remove_unused_imports._cross_file import analyze_cross_file
from remove_unused_imports._data import ImportInfo
from remove_unused_imports._detection import find_unused_imports
from remove_unused_imports._graph import build_import_graph
from remove_unused_imports._graph import build_import_graph_from_directory


def check_file(filepath: Path, fix: bool = False) -> tuple[int, list[str]]:
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

    if fix:
        new_source = remove_unused_imports(source, unused)
        if new_source != source:
            filepath.write_text(new_source)
            messages.append(
                f"Fixed {len(unused)} unused import(s) in {filepath}",
            )

    return len(unused), messages


def check_cross_file(
    path: Path,
    fix: bool = False,
    warn_implicit_reexports: bool = False,
    warn_circular: bool = False,
    quiet: bool = False,
) -> tuple[int, list[str]]:
    """Check imports across files (cross-file mode).

    Args:
        path: Entry point file or directory to analyze
        fix: Whether to fix unused imports
        warn_implicit_reexports: Whether to warn about implicit re-exports
        warn_circular: Whether to warn about circular imports
        quiet: Whether to suppress individual issue messages

    Returns:
        Tuple of (number of issues found, list of messages)
    """
    messages: list[str] = []

    # Build import graph
    if path.is_file():
        graph = build_import_graph(path)
    else:
        graph = build_import_graph_from_directory(path)

    # Analyze
    result = analyze_cross_file(graph)

    # Format results
    total_issues = 0

    # Unused imports
    for file_path, unused in sorted(result.unused_imports.items()):
        total_issues += len(unused)
        if not quiet:
            for imp in unused:
                if imp.is_from_import:
                    msg = f"{file_path}:{imp.lineno}: Unused import '{imp.name}' from '{imp.module}'"
                else:
                    msg = f"{file_path}:{imp.lineno}: Unused import '{imp.name}'"
                messages.append(msg)

        if fix:
            _fix_file(file_path, unused, messages)

    # Implicit re-exports (warnings)
    if warn_implicit_reexports and result.implicit_reexports:
        if not quiet:
            for reexport in result.implicit_reexports:
                used_by_names = ", ".join(str(p.name) for p in sorted(reexport.used_by))
                msg = (
                    f"{reexport.source_file}: "
                    f"Implicit re-export '{reexport.import_name}' "
                    f"(used by: {used_by_names}, not in __all__)"
                )
                messages.append(msg)

    # Circular imports (warnings)
    if warn_circular and result.circular_imports:
        if not quiet:
            for cycle in result.circular_imports:
                cycle_names = " -> ".join(str(p.name) for p in cycle)
                msg = f"Circular import: {cycle_names} -> {cycle[0].name}"
                messages.append(msg)

    return total_issues, messages


def _fix_file(
    file_path: Path,
    unused: list[ImportInfo],
    messages: list[str],
) -> None:
    """Fix unused imports in a file."""
    try:
        source = file_path.read_text()
    except (OSError, UnicodeDecodeError):
        return

    new_source = remove_unused_imports(source, unused)
    if new_source != source:
        file_path.write_text(new_source)
        messages.append(f"Fixed {len(unused)} unused import(s) in {file_path}")


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
  %(prog)s --fix main.py             Fix unused imports
  %(prog)s --warn-implicit-reexports main.py
  %(prog)s --warn-circular main.py
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
            f"\n{action} {total_unused} unused import(s) "
            f"in {total_files_with_issues} file(s)",
        )
        return 0 if args.fix else 1
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
        fix=args.fix,
        warn_implicit_reexports=args.warn_implicit_reexports,
        warn_circular=args.warn_circular,
        quiet=args.quiet,
    )

    if not args.quiet:
        for msg in messages:
            print(msg)

    if total_issues > 0:
        action = "Fixed" if args.fix else "Found"
        print(f"\n{action} {total_issues} unused import(s)")
        return 0 if args.fix else 1
    else:
        print("No unused imports found")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
