"""Tests for special import handling (__future__, __all__, TYPE_CHECKING)."""
from __future__ import annotations

import pytest

from remove_unused_imports import find_unused_imports


def _get_unused_names(source: str) -> set[str]:
    """Get set of unused import names from source code."""
    return {imp.name for imp in find_unused_imports(source)}


# =============================================================================
# __future__ imports
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Single __future__ import
        pytest.param(
            'from __future__ import annotations\n'
            '\n'
            'def func(x: int) -> str:\n'
            '    return str(x)\n',
            id='future annotations not flagged',
        ),
        # Multiple __future__ imports
        pytest.param(
            'from __future__ import annotations, division\n'
            'x = 1 / 2\n',
            id='multiple future imports not flagged',
        ),
        # All common __future__ imports
        pytest.param(
            'from __future__ import annotations\n'
            'from __future__ import division\n'
            'from __future__ import print_function\n'
            'from __future__ import absolute_import\n',
            id='all future imports not flagged',
        ),
    ),
)
def test_future_imports_noop(s):
    """Test that __future__ imports are NEVER flagged."""
    unused = _get_unused_names(s)
    # No __future__ import names should appear
    assert 'annotations' not in unused
    assert 'division' not in unused
    assert 'print_function' not in unused
    assert 'absolute_import' not in unused


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # __future__ with other unused imports
        pytest.param(
            'from __future__ import annotations\n'
            'import os\n',
            {'os'},
            id='future import with unused regular import',
        ),
        # __future__ with multiple other unused
        pytest.param(
            'from __future__ import annotations\n'
            'import os\n'
            'import sys\n',
            {'os', 'sys'},
            id='future import with multiple unused',
        ),
    ),
)
def test_future_imports_with_unused(s, expected):
    """Test that __future__ not flagged but other unused imports are."""
    assert _get_unused_names(s) == expected


# =============================================================================
# __all__ exports
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Single import in __all__
        pytest.param(
            'import uuid\n'
            '__all__ = ["uuid"]\n',
            id='import in __all__ list',
        ),
        # Multiple imports in __all__
        pytest.param(
            'import uuid\n'
            'import secrets\n'
            '__all__ = ["uuid", "secrets"]\n',
            id='multiple imports in __all__',
        ),
        # __all__ as tuple
        pytest.param(
            'import uuid\n'
            '__all__ = ("uuid",)\n',
            id='__all__ as tuple',
        ),
        # __all__ with augmented assignment
        pytest.param(
            'import uuid\n'
            'import secrets\n'
            '__all__ = ["uuid"]\n'
            '__all__ += ["secrets"]\n',
            id='__all__ with augmented assignment',
        ),
        # From-import in __all__
        pytest.param(
            'from pathlib import Path\n'
            '__all__ = ["Path"]\n',
            id='from-import in __all__',
        ),
    ),
)
def test_all_exports_noop(s):
    """Test that imports in __all__ are NOT flagged."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Partial __all__ coverage
        pytest.param(
            'import uuid\n'
            'import secrets\n'
            'import os\n'
            '__all__ = ["uuid", "secrets"]\n',
            {'os'},
            id='partial __all__ coverage',
        ),
        # __all__ with unrelated import
        pytest.param(
            'import uuid\n'
            'import sys\n'
            '__all__ = ["uuid"]\n',
            {'sys'},
            id='import not in __all__',
        ),
    ),
)
def test_all_exports_partial(s, expected):
    """Test that imports NOT in __all__ ARE flagged."""
    assert _get_unused_names(s) == expected


# =============================================================================
# TYPE_CHECKING blocks
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Unused import in TYPE_CHECKING block
        pytest.param(
            'from typing import TYPE_CHECKING\n'
            '\n'
            'if TYPE_CHECKING:\n'
            '    from pathlib import Path\n',
            {'Path'},
            id='unused import in TYPE_CHECKING',
        ),
        # Multiple unused in TYPE_CHECKING
        pytest.param(
            'from typing import TYPE_CHECKING\n'
            '\n'
            'if TYPE_CHECKING:\n'
            '    from pathlib import Path\n'
            '    from typing import Optional\n',
            {'Path', 'Optional'},
            id='multiple unused in TYPE_CHECKING',
        ),
    ),
)
def test_type_checking_unused(s, expected):
    """Test that unused TYPE_CHECKING imports ARE flagged."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    's',
    (
        # TYPE_CHECKING import used in string annotation
        pytest.param(
            'from typing import TYPE_CHECKING\n'
            '\n'
            'if TYPE_CHECKING:\n'
            '    from pathlib import Path\n'
            '\n'
            'def func() -> "Path":\n'
            '    pass\n',
            id='TYPE_CHECKING import used in string annotation',
        ),
        # TYPE_CHECKING import used in Optional string
        pytest.param(
            'from typing import TYPE_CHECKING, Optional\n'
            '\n'
            'if TYPE_CHECKING:\n'
            '    from pathlib import Path\n'
            '\n'
            'def func() -> Optional["Path"]:\n'
            '    pass\n',
            id='TYPE_CHECKING import used in Optional string',
        ),
    ),
)
def test_type_checking_used_in_string_annotation_noop(s):
    """Test that TYPE_CHECKING imports used in string annotations are NOT flagged."""
    unused = _get_unused_names(s)
    assert 'Path' not in unused


# =============================================================================
# noqa comments
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Standard noqa: F401
        pytest.param(
            'import os  # noqa: F401\n',
            id='noqa F401 standard format',
        ),
        # Bare noqa (no code)
        pytest.param(
            'import sys  # noqa\n',
            id='noqa bare',
        ),
        # Multiple codes including F401
        pytest.param(
            'import re  # noqa: E501, F401\n',
            id='noqa multiple codes with F401',
        ),
        # No space after #
        pytest.param(
            'from typing import List  #noqa: F401\n',
            id='noqa no space after hash',
        ),
        # Extra spaces
        pytest.param(
            'from typing import Dict  #  noqa:  F401\n',
            id='noqa extra spaces',
        ),
        # noqa keyword is case-insensitive
        pytest.param(
            'from collections import Counter  # NOQA: F401\n',
            id='noqa keyword uppercase',
        ),
        pytest.param(
            'from collections import OrderedDict  # NoQa: F401\n',
            id='noqa keyword mixed case',
        ),
        # Comma variations
        pytest.param(
            'from abc import ABC  # noqa: F401,E501\n',
            id='noqa comma no space',
        ),
        pytest.param(
            'from abc import ABCMeta  # noqa: F401 , E501\n',
            id='noqa comma with spaces',
        ),
        # noqa with trailing comment text
        pytest.param(
            'import os  # noqa: F401  imported for side effects\n',
            id='noqa with trailing comment text',
        ),
    ),
)
def test_noqa_f401_noop(s):
    """Test that imports with noqa: F401 are NOT flagged."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # noqa with wrong code
        pytest.param(
            'import json  # noqa: E501\n',
            {'json'},
            id='noqa wrong code',
        ),
        # noqa with lowercase code (codes are case-sensitive, matching flake8)
        pytest.param(
            'import pickle  # noqa: f401\n',
            {'pickle'},
            id='noqa lowercase code not recognized',
        ),
        # noqa on different line (doesn't apply)
        pytest.param(
            'import math\n'
            '# noqa: F401\n',
            {'math'},
            id='noqa on different line',
        ),
        # Mix of noqa and non-noqa
        pytest.param(
            'import os  # noqa: F401\n'
            'import sys\n',
            {'sys'},
            id='noqa mixed with non-noqa',
        ),
    ),
)
def test_noqa_f401_still_flagged(s, expected):
    """Test that noqa with wrong code or on wrong line still flags the import."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Multi-line import with noqa on individual names
        pytest.param(
            'from typing import (\n'
            '    List,  # noqa: F401\n'
            '    Dict,  # truly unused, no noqa\n'
            '    Set,  # noqa: F401\n'
            ')\n',
            {'Dict'},
            id='multiline import noqa on individual names',
        ),
        # Multi-line import with all noqa
        pytest.param(
            'from typing import (\n'
            '    List,  # noqa: F401\n'
            '    Dict,  # noqa: F401\n'
            ')\n',
            set(),
            id='multiline import all have noqa',
        ),
        # Backslash continuation with noqa on following line
        pytest.param(
            'import os \\\n'
            '# noqa: F401\n',
            set(),
            id='backslash continuation noqa on next line',
        ),
        # Backslash continuation with noqa on same line
        pytest.param(
            'import sys \\\n'
            '  # noqa: F401\n',
            set(),
            id='backslash continuation noqa with leading space',
        ),
        # Multiple continuation lines
        pytest.param(
            'import \\\n'
            '  os \\\n'
            '  # noqa: F401\n',
            set(),
            id='multiple continuation lines with noqa',
        ),
    ),
)
def test_noqa_multiline_imports(s, expected):
    """Test that noqa works on individual lines of multi-line imports."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Semicolon-separated imports with noqa
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Semicolon imports with noqa at end
        pytest.param(
            'import sys; import os  # noqa: F401\n',
            id='semicolon imports with noqa suppresses all',
        ),
        # Semicolon with from-import
        pytest.param(
            'import sys; from pathlib import Path  # noqa: F401\n',
            id='semicolon with from-import noqa',
        ),
        # Semicolon with bare noqa
        pytest.param(
            'import sys; import os  # noqa\n',
            id='semicolon imports with bare noqa',
        ),
    ),
)
def test_noqa_semicolon_imports_noop(s):
    """Test that noqa at end of line suppresses all semicolon-separated imports."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Semicolon imports where one is used
        pytest.param(
            'import sys; import os  # noqa: F401\n'
            'sys.argv\n',
            set(),
            id='semicolon imports one used one noqa',
        ),
        # Semicolon with continuation and noqa
        pytest.param(
            'import sys; import os \\\n'
            '  # noqa: F401\n'
            'sys.argv\n',
            set(),
            id='semicolon with continuation noqa',
        ),
    ),
)
def test_noqa_semicolon_with_usage(s, expected):
    """Test semicolon imports with mixed usage and noqa."""
    assert _get_unused_names(s) == expected
