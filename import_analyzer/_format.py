"""Output formatting for CLI."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from import_analyzer._cross_file import CrossFileResult
from import_analyzer._data import ImplicitReexport
from import_analyzer._data import ImportInfo
from import_analyzer._data import is_under_path

# Box drawing characters for nicer output
HORIZONTAL = "─"
DOUBLE_HORIZONTAL = "═"


def make_relative(path: Path, base: Path) -> str:
    """Make a path relative to base, or return as-is if not possible."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def format_cross_file_results(
    result: CrossFileResult,
    base_path: Path,
    fix_unused: bool = False,
    warn_implicit_reexports: bool = False,
    warn_circular: bool = False,
    warn_unreachable: bool = False,
    quiet: bool = False,
    fixed_files: dict[Path, int] | None = None,
) -> list[str]:
    """Format cross-file analysis results for display.

    Args:
        result: The cross-file analysis result
        base_path: Base path for making paths relative (also filters results)
        fix_unused: Whether we're in fix mode
        warn_implicit_reexports: Whether to show implicit re-export warnings
        warn_circular: Whether to show circular import warnings
        warn_unreachable: Whether to show unreachable file warnings
        quiet: Whether to suppress detailed output
        fixed_files: Dict of file -> count of imports fixed (for fix mode)

    Returns:
        List of formatted lines to print
    """
    lines: list[str] = []

    # Resolve base path for relative path calculation and filtering
    if base_path.is_file():
        base_path = base_path.parent
    base_path = base_path.resolve()

    # Filter results to only files under base_path
    # (graph may include files discovered via imports outside the target directory)
    filtered_unused = {
        fp: unused for fp, unused in result.unused_imports.items()
        if is_under_path(fp, base_path)
    }

    # Count totals (from filtered results)
    total_unused = sum(len(unused) for unused in filtered_unused.values())
    total_files = len(filtered_unused)

    # Section 1: Unused imports (grouped by file, then by line)
    if filtered_unused and not quiet:
        lines.extend(
            _format_unused_imports(filtered_unused, base_path, fix_unused, fixed_files),
        )

    # Section 2: Implicit re-exports (filtered to base_path)
    filtered_reexports = [
        r for r in result.implicit_reexports
        if is_under_path(r.source_file, base_path)
    ]
    if warn_implicit_reexports and filtered_reexports and not quiet:
        if lines:
            lines.append("")
        lines.extend(_format_implicit_reexports(filtered_reexports, base_path))

    # Section 3: Circular imports (filtered to cycles involving base_path files)
    filtered_cycles = [
        cycle for cycle in result.circular_imports
        if any(is_under_path(p, base_path) for p in cycle)
    ]
    if warn_circular and filtered_cycles and not quiet:
        if lines:
            lines.append("")
        lines.extend(_format_circular_imports(filtered_cycles, base_path))

    # Section 4: Unreachable files (filtered to base_path)
    filtered_unreachable = {
        fp for fp in result.unreachable_files
        if is_under_path(fp, base_path)
    }
    if warn_unreachable and filtered_unreachable and not quiet:
        if lines:
            lines.append("")
        lines.extend(_format_unreachable_files(filtered_unreachable, base_path))

    # Summary
    if lines:
        lines.append("")
    lines.extend(
        _format_summary(
            total_unused,
            total_files,
            len(filtered_unreachable) if warn_unreachable else 0,
            fix_unused,
        ),
    )

    return lines


def _format_unused_imports(
    unused_imports: dict[Path, list[ImportInfo]],
    base_path: Path,
    fix_unused: bool,
    fixed_files: dict[Path, int] | None,
) -> list[str]:
    """Format unused imports grouped by file and line."""
    lines: list[str] = []

    for file_path in sorted(unused_imports.keys()):
        unused = unused_imports[file_path]
        rel_path = make_relative(file_path, base_path)

        # Group imports by line number
        by_line: dict[int, list[ImportInfo]] = defaultdict(list)
        for imp in unused:
            by_line[imp.lineno].append(imp)

        # File header
        if lines:
            lines.append("")
        lines.append(rel_path)

        # Format each line's imports
        for lineno in sorted(by_line.keys()):
            imps = by_line[lineno]
            lines.extend(_format_line_imports(lineno, imps))

        # Add "fixed" note if applicable
        if fix_unused and fixed_files and file_path in fixed_files:
            count = fixed_files[file_path]
            lines.append(f"  └─ Fixed {count} import(s)")

    return lines


def _format_line_imports(lineno: int, imports: list[ImportInfo]) -> list[str]:
    """Format imports from a single line."""
    lines: list[str] = []

    # Group by module for from-imports
    by_module: dict[str, list[ImportInfo]] = defaultdict(list)
    regular_imports: list[ImportInfo] = []

    for imp in imports:
        if imp.is_from_import:
            by_module[imp.module].append(imp)
        else:
            regular_imports.append(imp)

    # Format regular imports (import X)
    for imp in regular_imports:
        lines.append(f"  {lineno:>4}: Unused import '{imp.name}'")

    # Format from-imports grouped by module
    for module, module_imports in sorted(by_module.items()):
        names = [imp.name for imp in module_imports]
        if len(names) == 1:
            lines.append(f"  {lineno:>4}: Unused '{names[0]}' from '{module}'")
        else:
            # Multiple imports from same module on same line
            formatted_names = _format_name_list(names, indent=10)
            lines.append(f"  {lineno:>4}: Unused from '{module}':")
            lines.append(f"          {formatted_names}")

    return lines


def _format_name_list(names: list[str], indent: int = 0, max_width: int = 70) -> str:
    """Format a list of names, wrapping if needed."""
    joined = ", ".join(sorted(names))
    if len(joined) <= max_width:
        return joined

    # Wrap to multiple lines
    result_lines: list[str] = []
    current_line: list[str] = []
    current_len = 0
    prefix = " " * indent

    for name in sorted(names):
        name_with_sep = name + ", "
        if current_len + len(name_with_sep) > max_width and current_line:
            result_lines.append(", ".join(current_line) + ",")
            current_line = []
            current_len = 0
        current_line.append(name)
        current_len += len(name_with_sep)

    if current_line:
        result_lines.append(", ".join(current_line))

    return ("\n" + prefix).join(result_lines)


def _format_implicit_reexports(
    reexports: list[ImplicitReexport],
    base_path: Path,
) -> list[str]:
    """Format implicit re-export warnings."""
    lines: list[str] = []

    # Header
    lines.append(HORIZONTAL * 79)
    lines.append("Implicit Re-exports (consider adding to __all__)")
    lines.append(HORIZONTAL * 79)

    # Group by source file
    by_file: dict[Path, list[ImplicitReexport]] = defaultdict(list)
    for reexport in reexports:
        by_file[reexport.source_file].append(reexport)

    for file_path in sorted(by_file.keys()):
        file_reexports = by_file[file_path]
        rel_path = make_relative(file_path, base_path)

        lines.append("")
        lines.append(rel_path)

        for reexport in sorted(file_reexports, key=lambda r: r.import_name):
            used_by_names = sorted(p.name for p in reexport.used_by)
            if len(used_by_names) <= 3:
                used_by_str = ", ".join(used_by_names)
            else:
                used_by_str = f"{', '.join(used_by_names[:3])}, ... (+{len(used_by_names) - 3} more)"
            lines.append(f"  • {reexport.import_name} (used by: {used_by_str})")

    return lines


def _format_circular_imports(
    cycles: list[list[Path]],
    base_path: Path,
) -> list[str]:
    """Format circular import warnings."""
    lines: list[str] = []

    # Header
    lines.append(HORIZONTAL * 79)
    lines.append("Circular Imports")
    lines.append(HORIZONTAL * 79)

    for cycle in cycles:
        lines.append("")
        if len(cycle) <= 5:
            # Short cycle - show full path
            cycle_parts = [make_relative(p, base_path) for p in cycle]
            cycle_parts.append(make_relative(cycle[0], base_path))  # Close the loop
            lines.append("• " + " → ".join(cycle_parts))
        else:
            # Long cycle - show abbreviated with key files
            first = make_relative(cycle[0], base_path)
            lines.append(f"• {first}")
            lines.append(f"  → ... ({len(cycle)} files in cycle)")
            lines.append(f"  → {first}")

    return lines


def _format_unreachable_files(
    unreachable_files: set[Path],
    base_path: Path,
) -> list[str]:
    """Format unreachable files warning."""
    lines: list[str] = []

    # Header
    lines.append(HORIZONTAL * 79)
    lines.append("Unreachable Files (will become dead code after fixing imports)")
    lines.append(HORIZONTAL * 79)

    # List files
    for file_path in sorted(unreachable_files):
        rel_path = make_relative(file_path, base_path)
        lines.append(f"  • {rel_path}")

    return lines


def _format_summary(
    total_unused: int,
    total_files: int,
    unreachable_count: int,
    fix_unused: bool,
) -> list[str]:
    """Format the summary line."""
    lines: list[str] = []
    lines.append(DOUBLE_HORIZONTAL * 79)

    if total_unused == 0 and unreachable_count == 0:
        lines.append("No unused imports found")
    else:
        parts: list[str] = []
        action = "Fixed" if fix_unused else "Found"

        if total_unused > 0:
            if total_files == 1:
                parts.append(f"{total_unused} unused import(s)")
            else:
                parts.append(f"{total_unused} unused import(s) in {total_files} file(s)")

        if unreachable_count > 0:
            parts.append(f"{unreachable_count} unreachable file(s)")

        lines.append(f"{action} {', '.join(parts)}")

    lines.append(DOUBLE_HORIZONTAL * 79)
    return lines
