from __future__ import annotations

import argparse
import sys
from pathlib import Path

from remove_unused_imports._autofix import remove_unused_imports
from remove_unused_imports._detection import find_unused_imports


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
            messages.append(
                f"Fixed {len(unused)} unused import(s) in {filepath}",
            )

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
            f"\n{action} {total_unused} unused import(s) "
            f"in {total_files_with_issues} file(s)",
        )
        return 0 if args.fix else 1
    else:
        print("No unused imports found")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
