"""Tests for autofix functionality."""
from __future__ import annotations

import pytest

from remove_unused_imports import find_unused_imports
from remove_unused_imports import remove_unused_imports

# =============================================================================
# Basic removal
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Remove single unused import
        pytest.param(
            'import os\n'
            'import sys\n'
            'x = os.getcwd()\n',
            'import os\n'
            'x = os.getcwd()\n',
            id='remove single unused import',
        ),
        # Remove multiple unused imports
        pytest.param(
            'import os\n'
            'import sys\n'
            'import json\n'
            'x = os.getcwd()\n',
            'import os\n'
            'x = os.getcwd()\n',
            id='remove multiple unused imports',
        ),
        # Remove unused from-import
        pytest.param(
            'from pathlib import Path\n'
            'from typing import Optional\n'
            'x: Optional[int] = None\n',
            'from typing import Optional\n'
            'x: Optional[int] = None\n',
            id='remove unused from-import',
        ),
        # Remove import with alias
        pytest.param(
            'import numpy as np\n'
            'import os\n'
            'x = os.getcwd()\n',
            'import os\n'
            'x = os.getcwd()\n',
            id='remove aliased import',
        ),
    ),
)
def test_autofix_removal(s, expected):
    """Test basic import removal."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Partial removal from multi-import
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Partial from-import removal
        pytest.param(
            'from typing import List, Dict, Optional\n'
            'x: Optional[int] = None\n',
            'from typing import Optional\n'
            'x: Optional[int] = None\n',
            id='partial from-import removal',
        ),
        # Partial removal with aliases
        pytest.param(
            'from itertools import chain as ch, cycle as cy, repeat as rp\n'
            'x = list(ch([1], [2]))\n',
            'from itertools import chain as ch\n'
            'x = list(ch([1], [2]))\n',
            id='partial removal with aliases',
        ),
    ),
)
def test_autofix_partial_removal(s, expected):
    """Test partial removal from multi-name imports."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


def test_autofix_partial_removal_multiple_kept():
    """Test partial removal keeps multiple used imports (order may vary)."""
    s = (
        'from typing import List, Dict, Optional\n'
        'x: Dict[str, List[int]]\n'
    )
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)

    # Check that Optional is removed and List, Dict are kept (order may vary)
    assert 'Optional' not in result
    assert 'List' in result
    assert 'Dict' in result
    assert 'from typing import' in result


# =============================================================================
# Empty block handling (pass insertion)
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Empty if block
        pytest.param(
            'if True:\n'
            '    import os\n'
            'x = 1\n',
            'if True:\n'
            '    pass\n'
            'x = 1\n',
            id='empty if block gets pass',
        ),
        # Empty try block
        pytest.param(
            'try:\n'
            '    import os\n'
            'except Exception:\n'
            '    pass\n',
            'try:\n'
            '    pass\n'
            'except Exception:\n'
            '    pass\n',
            id='empty try block gets pass',
        ),
        # Empty function body
        pytest.param(
            'def func():\n'
            '    import os\n',
            'def func():\n'
            '    pass\n',
            id='empty function gets pass',
        ),
        # Empty class body with import
        pytest.param(
            'class MyClass:\n'
            '    import os\n',
            'class MyClass:\n'
            '    pass\n',
            id='empty class gets pass',
        ),
        # Multiple imports in block all removed
        pytest.param(
            'if True:\n'
            '    import os\n'
            '    import sys\n'
            'x = 1\n',
            'if True:\n'
            '    pass\n'
            'x = 1\n',
            id='multiple imports removed from block gets single pass',
        ),
        # Nested block empty
        pytest.param(
            'def outer():\n'
            '    if True:\n'
            '        import os\n'
            '    return 1\n',
            'def outer():\n'
            '    if True:\n'
            '        pass\n'
            '    return 1\n',
            id='nested block gets pass',
        ),
    ),
)
def test_autofix_pass_insertion(s, expected):
    """Test that empty blocks get pass statements."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Indentation preservation
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Preserve indentation in class method
        pytest.param(
            'class MyClass:\n'
            '    def method(self):\n'
            '        from typing import List, Optional\n'
            '        x: Optional[int] = None\n',
            'class MyClass:\n'
            '    def method(self):\n'
            '        from typing import Optional\n'
            '        x: Optional[int] = None\n',
            id='preserve indentation in class method',
        ),
        # Preserve deep indentation
        pytest.param(
            'if True:\n'
            '    if True:\n'
            '        if True:\n'
            '            from typing import List, Optional\n'
            '            x: Optional[int] = None\n',
            'if True:\n'
            '    if True:\n'
            '        if True:\n'
            '            from typing import Optional\n'
            '            x: Optional[int] = None\n',
            id='preserve deep indentation',
        ),
    ),
)
def test_autofix_indentation(s, expected):
    """Test that indentation is preserved during autofix."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Multiline imports
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Multiline import with partial usage
        pytest.param(
            'from typing import (\n'
            '    List,\n'
            '    Dict,\n'
            '    Optional,\n'
            ')\n'
            'x: Optional[int] = None\n',
            id='multiline import partial removal',
        ),
    ),
)
def test_autofix_multiline(s):
    """Test multiline import handling."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    # Should have Optional but not List or Dict
    assert 'Optional' in result
    assert 'List' not in result
    assert 'Dict' not in result


# =============================================================================
# No changes needed
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # All imports used
        pytest.param(
            'import os\n'
            'x = os.getcwd()\n',
            id='all imports used',
        ),
        # Empty file
        pytest.param(
            '',
            id='empty file',
        ),
        # No imports
        pytest.param(
            'x = 1\n'
            'y = 2\n',
            id='no imports',
        ),
    ),
)
def test_autofix_no_changes(s):
    """Test that files with no unused imports are unchanged."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == s


# =============================================================================
# Complex scenarios
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Mixed used and unused across multiple statements
        pytest.param(
            'import os\n'
            'import sys\n'
            'from pathlib import Path\n'
            'from typing import Optional, List\n'
            '\n'
            'def func(p: Path) -> Optional[str]:\n'
            '    return str(p)\n',
            'from pathlib import Path\n'
            'from typing import Optional\n'
            '\n'
            'def func(p: Path) -> Optional[str]:\n'
            '    return str(p)\n',
            id='mixed used and unused complex',
        ),
    ),
)
def test_autofix_complex(s, expected):
    """Test complex autofix scenarios."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Additional empty block cases
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # For-else block becomes empty
        pytest.param(
            'for x in []:\n'
            '    pass\n'
            'else:\n'
            '    import os\n'
            'y = 1\n',
            'for x in []:\n'
            '    pass\n'
            'else:\n'
            '    pass\n'
            'y = 1\n',
            id='for else empty block gets pass',
        ),
        # While-else block becomes empty
        pytest.param(
            'while False:\n'
            '    pass\n'
            'else:\n'
            '    import os\n'
            'y = 1\n',
            'while False:\n'
            '    pass\n'
            'else:\n'
            '    pass\n'
            'y = 1\n',
            id='while else empty block gets pass',
        ),
        # If-else block becomes empty
        pytest.param(
            'if True:\n'
            '    pass\n'
            'else:\n'
            '    import os\n'
            'y = 1\n',
            'if True:\n'
            '    pass\n'
            'else:\n'
            '    pass\n'
            'y = 1\n',
            id='if else empty block gets pass',
        ),
        # Try finally becomes empty
        pytest.param(
            'try:\n'
            '    pass\n'
            'finally:\n'
            '    import os\n'
            'y = 1\n',
            'try:\n'
            '    pass\n'
            'finally:\n'
            '    pass\n'
            'y = 1\n',
            id='try finally empty block gets pass',
        ),
        # Except handler body becomes empty
        pytest.param(
            'try:\n'
            '    raise ValueError()\n'
            'except ValueError:\n'
            '    import os\n',
            'try:\n'
            '    raise ValueError()\n'
            'except ValueError:\n'
            '    pass\n',
            id='except handler empty block gets pass',
        ),
        # Async for body becomes empty
        pytest.param(
            'async def f():\n'
            '    async for x in gen():\n'
            '        import os\n',
            'async def f():\n'
            '    async for x in gen():\n'
            '        pass\n',
            id='async for empty block gets pass',
        ),
        # Async with body becomes empty
        pytest.param(
            'async def f():\n'
            '    async with ctx():\n'
            '        import os\n',
            'async def f():\n'
            '    async with ctx():\n'
            '        pass\n',
            id='async with empty block gets pass',
        ),
        # Try-else block becomes empty
        pytest.param(
            'try:\n'
            '    x = 1\n'
            'except ValueError:\n'
            '    pass\n'
            'else:\n'
            '    import os\n'
            'y = 1\n',
            'try:\n'
            '    x = 1\n'
            'except ValueError:\n'
            '    pass\n'
            'else:\n'
            '    pass\n'
            'y = 1\n',
            id='try else empty block gets pass',
        ),
    ),
)
def test_autofix_pass_insertion_edge_cases(s, expected):
    """Test pass insertion for various block types."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


def test_autofix_pass_insertion_multiline():
    """Test pass insertion when removing a multiline import from empty block."""
    s = (
        'try:\n'
        '    from os import (\n'
        '        path\n'
        '    )\n'
        'except Exception:\n'
        '    pass\n'
    )
    expected = (
        'try:\n'
        '    pass\n'
        'except Exception:\n'
        '    pass\n'
    )
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Partial removal from regular import statements
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Partial import removal (not from-import)
        pytest.param(
            'import os, sys, json\n'
            'x = os.getcwd()\n',
            'import os\n'
            'x = os.getcwd()\n',
            id='partial regular import removal',
        ),
        # Partial import with aliases
        pytest.param(
            'import numpy as np, pandas as pd, scipy as sp\n'
            'x = np.array([1])\n',
            'import numpy as np\n'
            'x = np.array([1])\n',
            id='partial import with aliases',
        ),
    ),
)
def test_autofix_partial_regular_import(s, expected):
    """Test partial removal from regular import statements."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Multi-line import full removal
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Full multi-line import removal
        pytest.param(
            'from typing import (\n'
            '    List,\n'
            '    Dict,\n'
            ')\n'
            'x = 1\n',
            'x = 1\n',
            id='full multiline import removal',
        ),
    ),
)
def test_autofix_multiline_full_removal(s, expected):
    """Test full removal of multi-line imports."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Relative imports
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Relative import partial removal
        pytest.param(
            'from . import foo, bar, baz\n'
            'x = foo()\n',
            'from . import foo\n'
            'x = foo()\n',
            id='relative import partial removal',
        ),
        # Relative import from submodule
        pytest.param(
            'from .submodule import a, b, c\n'
            'x = a()\n',
            'from .submodule import a\n'
            'x = a()\n',
            id='relative submodule import partial removal',
        ),
    ),
)
def test_autofix_relative_imports(s, expected):
    """Test autofix with relative imports."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Leading blank line handling
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Removal leaves multiple leading blank lines
        pytest.param(
            '\n'
            'import os\n'
            '\n'
            'x = 1\n',
            '\n'
            'x = 1\n',
            id='leading blank line preserved single',
        ),
    ),
)
def test_autofix_blank_line_cleanup(s, expected):
    """Test blank line cleanup after removal."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Semicolon handling (multiple statements on same line)
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Two unused imports on same line - can remove both
        pytest.param(
            'import os; import sys\n',
            '',
            id='two unused imports same line',
        ),
    ),
)
def test_autofix_semicolon_all_unused(s, expected):
    """Test that all-unused imports on same line get removed."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Import + statement on same line - surgically remove import
        pytest.param(
            'import os; x = 1\n',
            'x = 1\n',
            id='import then statement',
        ),
        # Statement + import on same line - surgically remove import
        pytest.param(
            'x = 1; import os\n',
            'x = 1\n',
            id='statement then import',
        ),
        # One used, one unused import on same line - remove unused
        pytest.param(
            'import os; import sys\nprint(os.getcwd())\n',
            'import os\nprint(os.getcwd())\n',
            id='mixed used unused imports same line',
        ),
        # From-import + statement - surgically remove import
        pytest.param(
            'from pathlib import Path; x = 1\n',
            'x = 1\n',
            id='from-import then statement',
        ),
    ),
)
def test_autofix_semicolon_surgical_removal(s, expected):
    """Test surgical removal of imports from semicolon-separated lines."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Multiple spaces around semicolon
        pytest.param(
            'import os  ;  x = 1\n',
            'x = 1\n',
            id='multiple spaces around semicolon',
        ),
        # Tabs around semicolon
        pytest.param(
            'import os\t;\tx = 1\n',
            'x = 1\n',
            id='tabs around semicolon',
        ),
        # Mixed whitespace around semicolon
        pytest.param(
            'import os \t ; \t x = 1\n',
            'x = 1\n',
            id='mixed whitespace around semicolon',
        ),
        # No spaces around semicolon
        pytest.param(
            'import os;x = 1\n',
            'x = 1\n',
            id='no spaces around semicolon',
        ),
        # Statement then import with tabs
        pytest.param(
            'x = 1\t;\timport os\n',
            'x = 1\n',
            id='statement then import with tabs',
        ),
        # Statement then import with multiple spaces
        pytest.param(
            'x = 1  ;  import os\n',
            'x = 1\n',
            id='statement then import with spaces',
        ),
        # Statement then import no spaces
        pytest.param(
            'x = 1;import os\n',
            'x = 1\n',
            id='statement then import no spaces',
        ),
    ),
)
def test_autofix_semicolon_whitespace_handling(s, expected):
    """Test surgical removal handles various whitespace around semicolons."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


# =============================================================================
# Backslash continuation handling
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Import with semicolon and backslash continuation
        pytest.param(
            'import os; \\\n    x = 1\n',
            'x = 1\n',
            id='import semicolon backslash continued',
        ),
        # Multiline import statement
        pytest.param(
            'import \\\n    os\nx = 1\n',
            'x = 1\n',
            id='multiline import statement',
        ),
        # Statement then backslash then import
        pytest.param(
            'x = 1; \\\nimport os\n',
            'x = 1\n',
            id='statement backslash import',
        ),
    ),
)
def test_autofix_backslash_continuation(s, expected):
    """Test removal handles backslash line continuations."""
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected


def test_autofix_multiline_import_ending_on_semicolon_line():
    """Test multiline import ending on same line as another statement."""
    s = 'import \\\n    sys; x = 1\n'
    expected = 'x = 1\n'
    unused = find_unused_imports(s)
    result = remove_unused_imports(s, unused)
    assert result == expected
