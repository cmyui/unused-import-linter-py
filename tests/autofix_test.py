"""Tests for autofix functionality."""
from __future__ import annotations

import pytest

from unused_import_linter import find_unused_imports
from unused_import_linter import remove_unused_imports

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
