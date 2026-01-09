"""Tests for basic unused import detection."""
from __future__ import annotations

import pytest

from remove_unused_imports import find_unused_imports


def _get_unused_names(source: str) -> set[str]:
    """Get set of unused import names from source code."""
    return {imp.name for imp in find_unused_imports(source)}


@pytest.mark.parametrize(
    's',
    (
        # Used in function call
        pytest.param(
            'import os\n'
            'x = os.getcwd()\n',
            id='used in function call',
        ),
        # Used in attribute access
        pytest.param(
            'import os\n'
            'x = os.environ\n',
            id='used in attribute access',
        ),
        # Used in assignment
        pytest.param(
            'from pathlib import Path\n'
            'p = Path(".")\n',
            id='used in assignment',
        ),
        # Used as decorator
        pytest.param(
            'from functools import lru_cache\n'
            '\n'
            '@lru_cache\n'
            'def func():\n'
            '    pass\n',
            id='used as decorator',
        ),
        # Used as base class
        pytest.param(
            'from abc import ABC\n'
            '\n'
            'class MyClass(ABC):\n'
            '    pass\n',
            id='used as base class',
        ),
        # Used in type annotation
        pytest.param(
            'from typing import Optional\n'
            '\n'
            'def func(x: Optional[int]) -> Optional[str]:\n'
            '    pass\n',
            id='used in type annotation',
        ),
        # Used in variable annotation
        pytest.param(
            'from pathlib import Path\n'
            'my_path: Path\n',
            id='used in variable annotation',
        ),
        # Used in class variable annotation
        pytest.param(
            'from typing import List\n'
            '\n'
            'class MyClass:\n'
            '    items: List[int]\n',
            id='used in class variable annotation',
        ),
        # Used in f-string
        pytest.param(
            'import sys\n'
            'msg = f"Python version: {sys.version}"\n',
            id='used in f-string expression',
        ),
        # Used in comprehension
        pytest.param(
            'import os\n'
            "files = [f for f in os.listdir('.')]\n",
            id='used in list comprehension',
        ),
        # Used in lambda
        pytest.param(
            'import math\n'
            'f = lambda x: math.sqrt(x)\n',
            id='used in lambda',
        ),
        # Used in default argument
        pytest.param(
            'import os\n'
            'def func(path=os.getcwd()):\n'
            '    pass\n',
            id='used in default argument',
        ),
        # Used in globals manipulation
        pytest.param(
            'import pprint\n'
            "globals()['pp'] = pprint.pprint\n",
            id='used in globals assignment',
        ),
        # Used in nested function
        pytest.param(
            'import os\n'
            '\n'
            'def outer():\n'
            '    def inner():\n'
            '        return os.getcwd()\n'
            '    return inner\n',
            id='used in nested function',
        ),
        # Used in class method
        pytest.param(
            'import os\n'
            '\n'
            'class MyClass:\n'
            '    def method(self):\n'
            '        return os.getcwd()\n',
            id='used in class method',
        ),
        # Used in async function
        pytest.param(
            'import asyncio\n'
            '\n'
            'async def main():\n'
            '    await asyncio.sleep(1)\n',
            id='used in async function',
        ),
        # Used before being shadowed
        pytest.param(
            'import os\n'
            'x = os.getcwd()\n'
            'os = "shadowed"\n',
            id='used before being shadowed',
        ),
    ),
)
def test_detection_noop(s):
    """Test that used imports are NOT flagged."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Simple unused import
        pytest.param(
            'import os\n',
            {'os'},
            id='simple unused import',
        ),
        # Simple unused from-import
        pytest.param(
            'from pathlib import Path\n',
            {'Path'},
            id='simple unused from-import',
        ),
        # Multiple unused imports
        pytest.param(
            'import os\n'
            'import sys\n'
            'import json\n',
            {'os', 'sys', 'json'},
            id='multiple unused imports',
        ),
        # Multiple unused from-imports
        pytest.param(
            'from pathlib import Path\n'
            'from typing import Optional\n'
            'from collections import defaultdict\n',
            {'Path', 'Optional', 'defaultdict'},
            id='multiple unused from-imports',
        ),
        # Multiple names single import
        pytest.param(
            'import os, sys, json\n',
            {'os', 'sys', 'json'},
            id='multiple names single import',
        ),
        # Multiple names single from-import
        pytest.param(
            'from typing import List, Dict, Tuple\n',
            {'List', 'Dict', 'Tuple'},
            id='multiple names single from-import',
        ),
        # Nested module import
        pytest.param(
            'import os.path\n',
            {'os'},
            id='nested module import binds top-level name',
        ),
        # Deeply nested module import
        pytest.param(
            'import xml.etree.ElementTree\n',
            {'xml'},
            id='deeply nested module import',
        ),
        # Submodule import
        pytest.param(
            'import collections.abc\n',
            {'collections'},
            id='submodule import',
        ),
        # From nested module
        pytest.param(
            'from os.path import join\n',
            {'join'},
            id='from nested module import',
        ),
        # Import in if block
        pytest.param(
            'if True:\n'
            '    import os\n',
            {'os'},
            id='import in if block',
        ),
        # Import in try block
        pytest.param(
            'try:\n'
            '    import optional_module\n'
            'except ImportError:\n'
            '    pass\n',
            {'optional_module'},
            id='import in try block',
        ),
        # Import in function
        pytest.param(
            'def func():\n'
            '    import os\n'
            '    return 42\n',
            {'os'},
            id='import inside function',
        ),
        # Import in class
        pytest.param(
            'class MyClass:\n'
            '    import os\n'
            '\n'
            '    def method(self):\n'
            '        pass\n',
            {'os'},
            id='import inside class',
        ),
        # Import in except handler
        pytest.param(
            'try:\n'
            '    x = 1\n'
            'except ImportError:\n'
            '    import fallback\n',
            {'fallback'},
            id='import in except handler',
        ),
        # Import in else block of try
        pytest.param(
            'try:\n'
            '    x = 1\n'
            'except Exception:\n'
            '    pass\n'
            'else:\n'
            '    import success_module\n',
            {'success_module'},
            id='import in try-else block',
        ),
        # Import in finally block
        pytest.param(
            'try:\n'
            '    x = 1\n'
            'finally:\n'
            '    import cleanup_module\n',
            {'cleanup_module'},
            id='import in finally block',
        ),
        # Import deleted immediately
        pytest.param(
            'import tempfile\n'
            'del tempfile\n',
            {'tempfile'},
            id='import deleted immediately',
        ),
        # Partial usage of multi-import
        pytest.param(
            'from typing import List, Dict, Optional\n'
            'x: Optional[int] = None\n',
            {'List', 'Dict'},
            id='partial usage of multi-import',
        ),
    ),
)
def test_detection(s, expected):
    """Test that unused imports ARE flagged."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    's',
    (
        # Empty file
        pytest.param(
            '',
            id='empty file',
        ),
        # File with only comments
        pytest.param(
            '# This is a comment\n'
            '# Another comment\n',
            id='file with only comments',
        ),
        # Star import
        pytest.param(
            'from os import *\n',
            id='star import not flagged',
        ),
    ),
)
def test_special_cases_noop(s):
    """Test special cases that should return no unused imports."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    's',
    (
        # Star import with unused regular import
        pytest.param(
            'from os import *\n'
            'import sys\n',
            id='star import with unused import',
        ),
    ),
)
def test_star_import_with_unused(s):
    """Star imports ignored but other unused imports still flagged."""
    unused = _get_unused_names(s)
    assert 'sys' in unused


@pytest.mark.parametrize(
    's',
    (
        pytest.param(
            'import os\n'
            'def broken(\n',
            id='syntax error incomplete function',
        ),
    ),
)
def test_syntax_error_returns_empty(s, capsys):
    """Files with syntax errors return empty list."""
    result = find_unused_imports(s)
    assert result == []
    captured = capsys.readouterr()
    assert 'Syntax error' in captured.err
