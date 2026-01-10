"""Tests for CLI functionality."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from import_analyzer._main import check_cross_file
from import_analyzer._main import check_file
from import_analyzer._main import collect_python_files
from import_analyzer._main import main

# =============================================================================
# check_file edge cases
# =============================================================================


@pytest.mark.skipif(sys.platform == 'win32', reason='chmod not effective on Windows')
def test_check_file_read_error(tmp_path):
    """Test handling of file read errors."""
    # Create a file and then make it unreadable
    filepath = tmp_path / "test.py"
    filepath.write_text("import os\n")
    filepath.chmod(0o000)

    try:
        count, messages = check_file(filepath)
        assert count == 0
        assert len(messages) == 1
        assert "Error reading" in messages[0]
    finally:
        # Restore permissions for cleanup
        filepath.chmod(0o644)


def test_check_file_unicode_error(tmp_path):
    """Test handling of files with invalid encoding."""
    filepath = tmp_path / "test.py"
    # Write binary data that's not valid UTF-8
    filepath.write_bytes(b'\xff\xfe invalid utf-8 \x80\x81')

    count, messages = check_file(filepath)
    assert count == 0
    assert len(messages) == 1
    assert "Error reading" in messages[0]


def test_check_file_regular_import_message(tmp_path):
    """Test message format for regular import (not from-import)."""
    filepath = tmp_path / "test.py"
    filepath.write_text("import os\n")

    count, messages = check_file(filepath)
    assert count == 1
    assert "Unused import 'os'" in messages[0]
    assert "from" not in messages[0]


# =============================================================================
# collect_python_files edge cases
# =============================================================================


def test_collect_non_python_file(tmp_path: Path) -> None:
    """Test that non-.py files are skipped."""
    # Create a non-Python file
    txt_file = tmp_path / "readme.txt"
    txt_file.write_text("hello")

    files = collect_python_files([txt_file])
    assert files == []


# =============================================================================
# CLI main() function
# =============================================================================


def test_main_no_files(tmp_path, monkeypatch, capsys):
    """Test main() with no Python files found (single-file mode)."""
    monkeypatch.setattr(
        sys, 'argv', ['prog', '--single-file', str(tmp_path / 'nonexistent')],
    )

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "No Python files found" in captured.err


def test_main_clean_files(tmp_path, monkeypatch, capsys):
    """Test main() with no unused imports."""
    clean_file = tmp_path / "clean.py"
    clean_file.write_text("import os\nprint(os.getcwd())\n")

    monkeypatch.setattr(sys, 'argv', ['prog', str(clean_file)])

    result = main()

    assert result == 0
    captured = capsys.readouterr()
    assert "No unused imports found" in captured.out


def test_main_with_unused(tmp_path, monkeypatch, capsys):
    """Test main() finding unused imports."""
    dirty_file = tmp_path / "dirty.py"
    dirty_file.write_text("import os\nimport sys\n")

    monkeypatch.setattr(sys, 'argv', ['prog', str(dirty_file)])

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "Unused import 'os'" in captured.out
    assert "Unused import 'sys'" in captured.out
    assert "Found 2 unused import(s)" in captured.out


def test_main_with_fix(tmp_path, monkeypatch, capsys):
    """Test main() with --fix-unused-imports flag."""
    dirty_file = tmp_path / "dirty.py"
    dirty_file.write_text("import os\nprint('hello')\n")

    monkeypatch.setattr(sys, 'argv', ['prog', '--fix-unused-imports', str(dirty_file)])

    result = main()

    assert result == 0
    captured = capsys.readouterr()
    assert "Fixed 1 unused import(s)" in captured.out

    # Verify file was modified
    assert dirty_file.read_text() == "print('hello')\n"


def test_main_quiet_mode(tmp_path, monkeypatch, capsys):
    """Test main() with --quiet flag."""
    dirty_file = tmp_path / "dirty.py"
    dirty_file.write_text("import os\nimport sys\n")

    monkeypatch.setattr(sys, 'argv', ['prog', '-q', str(dirty_file)])

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    # In quiet mode, individual issues are not printed
    assert "Unused import 'os'" not in captured.out
    # But summary is still shown
    assert "Found 2 unused import(s)" in captured.out


def test_main_multiple_files(tmp_path, monkeypatch, capsys):
    """Test main() with multiple files (single-file mode)."""
    file1 = tmp_path / "file1.py"
    file1.write_text("import os\n")
    file2 = tmp_path / "file2.py"
    file2.write_text("import sys\n")

    monkeypatch.setattr(
        sys, 'argv', ['prog', '--single-file', str(file1), str(file2)],
    )

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "Found 2 unused import(s) in 2 file(s)" in captured.out


def test_main_directory(tmp_path, monkeypatch, capsys):
    """Test main() with directory argument."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "test.py").write_text("import os\n")

    monkeypatch.setattr(sys, 'argv', ['prog', str(tmp_path)])

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "Found 1 unused import(s)" in captured.out


# =============================================================================
# CLI as subprocess (tests __main__.py)
# =============================================================================


def test_cli_subprocess(tmp_path):
    """Test running as python -m import_analyzer."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import os\n")

    result = subprocess.run(
        [sys.executable, '-m', 'import_analyzer', str(test_file)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )

    assert result.returncode == 1
    assert result.stdout is not None
    assert "Unused import 'os'" in result.stdout


# =============================================================================
# Cross-file mode: check_cross_file function tests
# =============================================================================


def test_cross_file_reexport_not_unused(tmp_path):
    """Re-exported imports should not be marked as unused."""
    # main.py imports List from utils
    (tmp_path / "main.py").write_text(
        "from utils import List\nx: List[int] = []\n",
    )
    # utils.py imports List from typing and re-exports it
    (tmp_path / "utils.py").write_text(
        "from typing import List, Dict  # Dict is unused\n",
    )

    count, messages = check_cross_file(tmp_path / "main.py")

    # Only Dict should be unused, not List
    assert count == 1
    message_text = " ".join(messages)
    assert "Dict" in message_text
    assert "List" not in message_text or "Implicit" in message_text


def test_cross_file_fix_preserves_reexports(tmp_path):
    """--fix-unused-imports should preserve re-exported imports."""
    (tmp_path / "main.py").write_text(
        "from utils import List\nx: List[int] = []\n",
    )
    (tmp_path / "utils.py").write_text(
        "from typing import List, Dict\n",
    )

    check_cross_file(tmp_path / "main.py", fix_unused=True)

    # List should be preserved (re-exported), Dict removed
    utils_content = (tmp_path / "utils.py").read_text()
    assert "List" in utils_content
    assert "Dict" not in utils_content


def test_cross_file_warn_implicit_reexports(tmp_path):
    """--warn-implicit-reexports should warn about re-exports not in __all__."""
    (tmp_path / "main.py").write_text(
        "from utils import List\nx: List[int] = []\n",
    )
    (tmp_path / "utils.py").write_text("from typing import List\n")

    count, messages = check_cross_file(
        tmp_path / "main.py", warn_implicit_reexports=True,
    )

    message_text = " ".join(messages)
    assert "Implicit Re-exports" in message_text
    assert "List" in message_text


def test_cross_file_warn_circular(tmp_path):
    """--warn-circular should report circular imports."""
    (tmp_path / "a.py").write_text("from b import x\ny = 1\n")
    (tmp_path / "b.py").write_text("from a import y\nx = 2\n")

    count, messages = check_cross_file(tmp_path / "a.py", warn_circular=True)

    message_text = " ".join(messages)
    assert "Circular Imports" in message_text


def test_cross_file_directory_mode(tmp_path):
    """Directory mode should analyze all files."""
    subdir = tmp_path / "pkg"
    subdir.mkdir()
    (subdir / "__init__.py").write_text("")
    (subdir / "module.py").write_text("import os\n")

    count, messages = check_cross_file(tmp_path)

    assert count == 1
    message_text = " ".join(messages)
    assert "os" in message_text


# =============================================================================
# Cross-file mode: main() CLI tests
# =============================================================================


def test_main_cross_file_nonexistent(tmp_path, monkeypatch, capsys):
    """Cross-file mode should error on non-existent path."""
    monkeypatch.setattr(
        sys, 'argv', ['prog', str(tmp_path / 'nonexistent')],
    )

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "Path not found" in captured.err


def test_main_cross_file_multiple_paths_error(tmp_path, monkeypatch, capsys):
    """Cross-file mode should error with multiple paths."""
    file1 = tmp_path / "a.py"
    file2 = tmp_path / "b.py"
    file1.write_text("")
    file2.write_text("")

    monkeypatch.setattr(sys, 'argv', ['prog', str(file1), str(file2)])

    result = main()

    assert result == 1
    captured = capsys.readouterr()
    assert "single entry point" in captured.err


def test_main_cross_file_with_warn_implicit_reexports(tmp_path, monkeypatch, capsys):
    """Test --warn-implicit-reexports flag via CLI."""
    (tmp_path / "main.py").write_text(
        "from utils import List\nx: List[int] = []\n",
    )
    (tmp_path / "utils.py").write_text("from typing import List\n")

    monkeypatch.setattr(
        sys,
        'argv',
        ['prog', '--warn-implicit-reexports', str(tmp_path / "main.py")],
    )

    main()

    captured = capsys.readouterr()
    assert "Implicit Re-exports" in captured.out


def test_main_cross_file_with_warn_circular(tmp_path, monkeypatch, capsys):
    """Test --warn-circular flag via CLI."""
    (tmp_path / "a.py").write_text("from b import x\ny = 1\n")
    (tmp_path / "b.py").write_text("from a import y\nx = 2\n")

    monkeypatch.setattr(
        sys, 'argv', ['prog', '--warn-circular', str(tmp_path / "a.py")],
    )

    main()

    captured = capsys.readouterr()
    assert "Circular Imports" in captured.out


def test_main_cross_file_fix(tmp_path, monkeypatch, capsys):
    """Test --fix-unused-imports in cross-file mode."""
    (tmp_path / "main.py").write_text(
        "from utils import List\nx: List[int] = []\n",
    )
    (tmp_path / "utils.py").write_text("from typing import List, Dict\n")

    monkeypatch.setattr(
        sys, 'argv', ['prog', '--fix-unused-imports', str(tmp_path / "main.py")],
    )

    result = main()

    assert result == 0
    captured = capsys.readouterr()
    assert "Fixed" in captured.out

    # Verify Dict was removed but List preserved
    utils_content = (tmp_path / "utils.py").read_text()
    assert "List" in utils_content
    assert "Dict" not in utils_content


def test_main_cross_file_quiet(tmp_path, monkeypatch, capsys):
    """Test --quiet in cross-file mode."""
    (tmp_path / "main.py").write_text("import os\n")

    monkeypatch.setattr(
        sys, 'argv', ['prog', '-q', str(tmp_path / "main.py")],
    )

    main()

    captured = capsys.readouterr()
    # Individual issues not shown
    assert "Unused import 'os'" not in captured.out
    # Summary shown
    assert "Found 1 unused import(s)" in captured.out


# =============================================================================
# Cross-file mode: edge cases
# =============================================================================


def test_cross_file_no_python_files_in_directory(tmp_path, monkeypatch, capsys):
    """Cross-file mode with directory containing no Python files."""
    # Create a directory with only non-Python files
    (tmp_path / "readme.txt").write_text("hello")
    (tmp_path / "data.json").write_text("{}")

    monkeypatch.setattr(sys, 'argv', ['prog', str(tmp_path)])

    result = main()

    assert result == 0
    captured = capsys.readouterr()
    assert "No unused imports found" in captured.out


def test_cross_file_syntax_error_in_imported_file(tmp_path):
    """Should handle syntax errors in imported files gracefully."""
    (tmp_path / "main.py").write_text("import broken\n")
    (tmp_path / "broken.py").write_text("def invalid syntax\n")

    # Should not raise, but may not detect the import as resolved
    count, messages = check_cross_file(tmp_path / "main.py")
    # The behavior is that broken.py won't be parsed, so import won't resolve
    # main.py's import of 'broken' will be seen as unused (can't resolve)
    assert count >= 0  # Just ensure no crash


def test_cross_file_empty_project(tmp_path):
    """Should handle empty files."""
    (tmp_path / "main.py").write_text("")

    count, messages = check_cross_file(tmp_path / "main.py")

    assert count == 0
    # Messages now includes summary even when no issues
    message_text = " ".join(messages)
    assert "No unused imports found" in message_text


def test_cross_file_nested_directories(tmp_path):
    """Directory mode should find files in nested directories."""
    pkg = tmp_path / "pkg"
    sub = pkg / "subpkg"
    sub.mkdir(parents=True)

    (pkg / "__init__.py").write_text("")
    (pkg / "module.py").write_text("import os\n")
    (sub / "__init__.py").write_text("")
    (sub / "deep.py").write_text("import sys\n")

    count, messages = check_cross_file(tmp_path)

    assert count == 2  # os and sys
    message_text = " ".join(messages)
    assert "os" in message_text
    assert "sys" in message_text
