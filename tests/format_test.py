"""Tests for output formatting (_format.py)."""

from __future__ import annotations

from pathlib import Path

from remove_unused_imports._cross_file import CrossFileResult
from remove_unused_imports._data import ImplicitReexport
from remove_unused_imports._data import ImportInfo
from remove_unused_imports._format import format_cross_file_results
from remove_unused_imports._format import make_relative


def test_make_relative_when_under_base():
    """Should return relative path when under base."""
    base = Path("/project/src")
    path = Path("/project/src/pkg/module.py")
    # Use Path to normalize separators for cross-platform comparison
    assert Path(make_relative(path, base)) == Path("pkg/module.py")


def test_make_relative_when_not_under_base():
    """Should return absolute path when not under base."""
    base = Path("/project/src")
    path = Path("/other/location/module.py")
    # Use Path to normalize separators for cross-platform comparison
    assert Path(make_relative(path, base)) == Path("/other/location/module.py")


def test_format_groups_by_file():
    """Should group unused imports by file."""
    result = CrossFileResult()
    file1 = Path("/project/src/a.py")
    file2 = Path("/project/src/b.py")
    result.unused_imports = {
        file1: [
            ImportInfo(
                name="os", module="", original_name="os",
                lineno=1, col_offset=0, end_lineno=1, end_col_offset=9,
                is_from_import=False, full_node_lineno=1, full_node_end_lineno=1,
            ),
        ],
        file2: [
            ImportInfo(
                name="sys", module="", original_name="sys",
                lineno=1, col_offset=0, end_lineno=1, end_col_offset=10,
                is_from_import=False, full_node_lineno=1, full_node_end_lineno=1,
            ),
        ],
    }

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"), fix=False,
    )
    output = "\n".join(lines)

    assert "a.py" in output
    assert "b.py" in output
    assert "os" in output
    assert "sys" in output


def test_format_groups_same_line_imports():
    """Should group imports from same line together."""
    result = CrossFileResult()
    file1 = Path("/project/src/module.py")
    result.unused_imports = {
        file1: [
            ImportInfo(
                name="List", module="typing", original_name="List",
                lineno=1, col_offset=0, end_lineno=1, end_col_offset=25,
                is_from_import=True, full_node_lineno=1, full_node_end_lineno=1,
            ),
            ImportInfo(
                name="Dict", module="typing", original_name="Dict",
                lineno=1, col_offset=0, end_lineno=1, end_col_offset=25,
                is_from_import=True, full_node_lineno=1, full_node_end_lineno=1,
            ),
        ],
    }

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"), fix=False,
    )
    output = "\n".join(lines)

    # Should show both names together with "from 'typing'"
    assert "typing" in output
    assert "List" in output
    assert "Dict" in output


def test_format_implicit_reexports_section():
    """Should format implicit re-exports in a separate section."""
    result = CrossFileResult()
    result.implicit_reexports = [
        ImplicitReexport(
            source_file=Path("/project/src/utils.py"),
            import_name="helper",
            used_by={Path("/project/src/main.py")},
        ),
    ]

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"),
        warn_implicit_reexports=True, fix=False,
    )
    output = "\n".join(lines)

    assert "Implicit Re-exports" in output
    assert "helper" in output
    assert "main.py" in output


def test_format_circular_imports_section():
    """Should format circular imports in a separate section."""
    result = CrossFileResult()
    result.circular_imports = [
        [
            Path("/project/src/a.py"),
            Path("/project/src/b.py"),
        ],
    ]

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"),
        warn_circular=True, fix=False,
    )
    output = "\n".join(lines)

    assert "Circular Imports" in output
    assert "a.py" in output
    assert "b.py" in output


def test_format_long_cycle_abbreviated():
    """Should abbreviate long circular import cycles."""
    result = CrossFileResult()
    # Create a cycle with 10 files
    cycle = [Path(f"/project/src/{chr(ord('a') + i)}.py") for i in range(10)]
    result.circular_imports = [cycle]

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"),
        warn_circular=True, fix=False,
    )
    output = "\n".join(lines)

    assert "Circular Imports" in output
    assert "10 files in cycle" in output


def test_format_summary_when_no_issues():
    """Should show 'no issues' message when nothing found."""
    result = CrossFileResult()

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"), fix=False,
    )
    output = "\n".join(lines)

    assert "No unused imports found" in output


def test_format_summary_with_issues():
    """Should show count in summary."""
    result = CrossFileResult()
    file1 = Path("/project/src/a.py")
    result.unused_imports = {
        file1: [
            ImportInfo(
                name="os", module="", original_name="os",
                lineno=1, col_offset=0, end_lineno=1, end_col_offset=9,
                is_from_import=False, full_node_lineno=1, full_node_end_lineno=1,
            ),
        ],
    }

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"), fix=False,
    )
    output = "\n".join(lines)

    assert "Found 1 unused import(s)" in output


def test_format_quiet_mode_shows_only_summary():
    """Quiet mode should only show summary."""
    result = CrossFileResult()
    file1 = Path("/project/src/a.py")
    result.unused_imports = {
        file1: [
            ImportInfo(
                name="os", module="", original_name="os",
                lineno=1, col_offset=0, end_lineno=1, end_col_offset=9,
                is_from_import=False, full_node_lineno=1, full_node_end_lineno=1,
            ),
        ],
    }

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"), fix=False, quiet=True,
    )
    output = "\n".join(lines)

    # Should have summary but not file details
    assert "Found 1 unused import(s)" in output
    assert "a.py" not in output


def test_format_fixed_shows_fixed_count():
    """Should show 'Fixed' instead of 'Found' in fix mode."""
    result = CrossFileResult()
    file1 = Path("/project/src/a.py")
    result.unused_imports = {
        file1: [
            ImportInfo(
                name="os", module="", original_name="os",
                lineno=1, col_offset=0, end_lineno=1, end_col_offset=9,
                is_from_import=False, full_node_lineno=1, full_node_end_lineno=1,
            ),
        ],
    }

    lines = format_cross_file_results(
        result, base_path=Path("/project/src"),
        fix=True, fixed_files={file1: 1},
    )
    output = "\n".join(lines)

    assert "Fixed 1 unused import(s)" in output
