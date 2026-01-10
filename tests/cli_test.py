"""Tests for CLI functionality."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from remove_unused_imports._main import check_file
from remove_unused_imports._main import collect_python_files
from remove_unused_imports._main import main

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
    """Test main() with --fix flag."""
    dirty_file = tmp_path / "dirty.py"
    dirty_file.write_text("import os\nprint('hello')\n")

    monkeypatch.setattr(sys, 'argv', ['prog', '--fix', str(dirty_file)])

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
    """Test running as python -m remove_unused_imports."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import os\n")

    result = subprocess.run(
        [sys.executable, '-m', 'remove_unused_imports', str(test_file)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Unused import 'os'" in result.stdout
