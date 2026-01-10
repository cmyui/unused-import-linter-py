"""Tests for file and directory operations."""
from __future__ import annotations

import pytest

from import_analyzer import check_file
from import_analyzer import collect_python_files

# =============================================================================
# check_file
# =============================================================================


@pytest.mark.parametrize(
    ('content', 'expected_count', 'expected_in_messages'),
    (
        # File with unused imports
        pytest.param(
            'import os\n'
            'import sys\n'
            'x = os.getcwd()\n',
            1,
            ['sys'],
            id='file with one unused import',
        ),
        # File with multiple unused imports
        pytest.param(
            'import os\n'
            'import sys\n'
            'import json\n',
            3,
            ['os', 'sys', 'json'],
            id='file with multiple unused imports',
        ),
        # File with partial from-import unused
        pytest.param(
            'from typing import List, Dict, Optional\n'
            'x: Optional[int] = None\n',
            2,
            ['List', 'Dict'],
            id='file with partial from-import unused',
        ),
    ),
)
def test_check_file_finds_unused(tmp_path, content, expected_count, expected_in_messages):
    """Test that check_file correctly identifies unused imports."""
    file_path = tmp_path / 'test.py'
    file_path.write_text(content)

    count, messages = check_file(file_path, fix_unused=False)

    assert count == expected_count
    message_text = '\n'.join(messages)
    for expected in expected_in_messages:
        assert expected in message_text


@pytest.mark.parametrize(
    ('content', 'should_not_contain', 'should_contain'),
    (
        # Fix removes unused
        pytest.param(
            'import os\n'
            'import sys\n'
            'x = os.getcwd()\n',
            'import sys',
            'import os',
            id='fix removes unused import',
        ),
        # Fix partial from-import
        pytest.param(
            'from typing import List, Dict, Optional\n'
            'x: Optional[int] = None\n',
            'List',
            'Optional',
            id='fix partial from-import',
        ),
    ),
)
def test_check_file_fixes(tmp_path, content, should_not_contain, should_contain):
    """Test that check_file with fix_unused=True removes unused imports."""
    file_path = tmp_path / 'test.py'
    file_path.write_text(content)

    check_file(file_path, fix_unused=True)

    new_content = file_path.read_text()
    assert should_not_contain not in new_content
    assert should_contain in new_content


def test_check_file_clean(tmp_path):
    """Test that check_file returns 0 for clean file."""
    content = 'import os\nx = os.getcwd()\n'
    file_path = tmp_path / 'test.py'
    file_path.write_text(content)

    count, messages = check_file(file_path, fix_unused=False)

    assert count == 0
    assert messages == []


def test_check_file_preserves_valid_python(tmp_path):
    """Test that fixed files are still valid Python."""
    content = '''import os
import sys

def get_home():
    return os.environ.get("HOME", "/")

if __name__ == "__main__":
    print(get_home())
'''
    file_path = tmp_path / 'test.py'
    file_path.write_text(content)

    check_file(file_path, fix_unused=True)

    fixed_content = file_path.read_text()
    # Should compile without errors
    compile(fixed_content, str(file_path), 'exec')
    # sys should be removed
    assert 'import sys' not in fixed_content
    # os should remain
    assert 'import os' in fixed_content


# =============================================================================
# collect_python_files
# =============================================================================


def test_collect_single_file(tmp_path):
    """Test collecting a single Python file."""
    file_path = tmp_path / 'test.py'
    file_path.write_text('import os\n')

    files = collect_python_files([file_path])

    assert files == [file_path]


def test_collect_directory(tmp_path):
    """Test collecting all Python files from a directory."""
    # Create files
    (tmp_path / 'a.py').write_text('import os\n')
    (tmp_path / 'b.py').write_text('import sys\n')
    (tmp_path / 'not_python.txt').write_text('hello\n')

    files = collect_python_files([tmp_path])

    assert len(files) == 2
    assert all(f.suffix == '.py' for f in files)


def test_collect_recursive(tmp_path):
    """Test recursive collection of Python files."""
    # Create nested structure
    (tmp_path / 'root.py').write_text('import os\n')
    subdir = tmp_path / 'subdir'
    subdir.mkdir()
    (subdir / 'nested.py').write_text('import sys\n')
    subsubdir = subdir / 'subsubdir'
    subsubdir.mkdir()
    (subsubdir / 'deep.py').write_text('import json\n')

    files = collect_python_files([tmp_path])

    assert len(files) == 3
    names = {f.name for f in files}
    assert names == {'root.py', 'nested.py', 'deep.py'}


def test_collect_ignores_non_python(tmp_path):
    """Test that non-Python files are ignored."""
    (tmp_path / 'test.txt').write_text('import os\n')
    (tmp_path / 'test.js').write_text('import os\n')
    (tmp_path / 'test.pyc').write_text('binary\n')

    files = collect_python_files([tmp_path])

    assert files == []


def test_collect_multiple_paths(tmp_path):
    """Test collecting from multiple paths."""
    dir1 = tmp_path / 'dir1'
    dir1.mkdir()
    (dir1 / 'a.py').write_text('import os\n')

    dir2 = tmp_path / 'dir2'
    dir2.mkdir()
    (dir2 / 'b.py').write_text('import sys\n')

    single_file = tmp_path / 'single.py'
    single_file.write_text('import json\n')

    files = collect_python_files([dir1, dir2, single_file])

    assert len(files) == 3


def test_collect_empty_directory(tmp_path):
    """Test collecting from empty directory."""
    empty_dir = tmp_path / 'empty'
    empty_dir.mkdir()

    files = collect_python_files([empty_dir])

    assert files == []


def test_collect_nonexistent_skipped(tmp_path):
    """Test that non-.py files passed directly are skipped."""
    txt_file = tmp_path / 'test.txt'
    txt_file.write_text('not python\n')

    files = collect_python_files([txt_file])

    assert files == []
