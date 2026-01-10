"""Tests for output formatting (_format.py)."""

from __future__ import annotations

from pathlib import Path

from import_analyzer._cross_file import CrossFileResult
from import_analyzer._data import ImplicitReexport
from import_analyzer._data import ImportInfo
from import_analyzer._format import format_cross_file_results
from import_analyzer._format import make_relative


def test_make_relative_when_under_base(tmp_path: Path) -> None:
    """Should return relative path when under base."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    path = base / "pkg" / "module.py"
    path.parent.mkdir(parents=True)
    path.touch()
    assert Path(make_relative(path, base)) == Path("pkg/module.py")


def test_make_relative_when_not_under_base(tmp_path: Path) -> None:
    """Should return absolute path when not under base."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    path = tmp_path / "other" / "location" / "module.py"
    path.parent.mkdir(parents=True)
    path.touch()
    # When not under base, returns the full path
    result = make_relative(path, base)
    assert "module.py" in result


def test_format_groups_by_file(tmp_path: Path) -> None:
    """Should group unused imports by file."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    file1 = base / "a.py"
    file2 = base / "b.py"
    file1.touch()
    file2.touch()

    result = CrossFileResult()
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
        result, base_path=base, fix_unused=False,
    )
    output = "\n".join(lines)

    assert "a.py" in output
    assert "b.py" in output
    assert "os" in output
    assert "sys" in output


def test_format_groups_same_line_imports(tmp_path: Path) -> None:
    """Should group imports from same line together."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    file1 = base / "module.py"
    file1.touch()

    result = CrossFileResult()
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
        result, base_path=base, fix_unused=False,
    )
    output = "\n".join(lines)

    # Should show both names together with "from 'typing'"
    assert "typing" in output
    assert "List" in output
    assert "Dict" in output


def test_format_implicit_reexports_section(tmp_path: Path) -> None:
    """Should format implicit re-exports in a separate section."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    utils_file = base / "utils.py"
    main_file = base / "main.py"
    utils_file.touch()
    main_file.touch()

    result = CrossFileResult()
    result.implicit_reexports = [
        ImplicitReexport(
            source_file=utils_file,
            import_name="helper",
            used_by={main_file},
        ),
    ]

    lines = format_cross_file_results(
        result, base_path=base,
        warn_implicit_reexports=True, fix_unused=False,
    )
    output = "\n".join(lines)

    assert "Implicit Re-exports" in output
    assert "helper" in output
    assert "main.py" in output


def test_format_circular_imports_section(tmp_path: Path) -> None:
    """Should format circular imports in a separate section."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    file_a = base / "a.py"
    file_b = base / "b.py"
    file_a.touch()
    file_b.touch()

    result = CrossFileResult()
    result.circular_imports = [[file_a, file_b]]

    lines = format_cross_file_results(
        result, base_path=base,
        warn_circular=True, fix_unused=False,
    )
    output = "\n".join(lines)

    assert "Circular Imports" in output
    assert "a.py" in output
    assert "b.py" in output


def test_format_long_cycle_abbreviated(tmp_path: Path) -> None:
    """Should abbreviate long circular import cycles."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    # Create a cycle with 10 files
    cycle = []
    for i in range(10):
        f = base / f"{chr(ord('a') + i)}.py"
        f.touch()
        cycle.append(f)

    result = CrossFileResult()
    result.circular_imports = [cycle]

    lines = format_cross_file_results(
        result, base_path=base,
        warn_circular=True, fix_unused=False,
    )
    output = "\n".join(lines)

    assert "Circular Imports" in output
    assert "10 files in cycle" in output


def test_format_summary_when_no_issues(tmp_path: Path) -> None:
    """Should show 'no issues' message when nothing found."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)

    result = CrossFileResult()

    lines = format_cross_file_results(
        result, base_path=base, fix_unused=False,
    )
    output = "\n".join(lines)

    assert "No unused imports found" in output


def test_format_summary_with_issues(tmp_path: Path) -> None:
    """Should show count in summary."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    file1 = base / "a.py"
    file1.touch()

    result = CrossFileResult()
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
        result, base_path=base, fix_unused=False,
    )
    output = "\n".join(lines)

    assert "Found 1 unused import(s)" in output


def test_format_quiet_mode_shows_only_summary(tmp_path: Path) -> None:
    """Quiet mode should only show summary."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    file1 = base / "a.py"
    file1.touch()

    result = CrossFileResult()
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
        result, base_path=base, fix_unused=False, quiet=True,
    )
    output = "\n".join(lines)

    # Should have summary but not file details
    assert "Found 1 unused import(s)" in output
    assert "a.py" not in output


def test_format_fixed_shows_fixed_count(tmp_path: Path) -> None:
    """Should show 'Fixed' instead of 'Found' in fix mode."""
    base = tmp_path / "project" / "src"
    base.mkdir(parents=True)
    file1 = base / "a.py"
    file1.touch()

    result = CrossFileResult()
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
        result, base_path=base,
        fix_unused=True, fixed_files={file1: 1},
    )
    output = "\n".join(lines)

    assert "Fixed 1 unused import(s)" in output
