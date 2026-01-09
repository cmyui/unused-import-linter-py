"""Tests for shadowed import detection."""
from __future__ import annotations

import pytest

from remove_unused_imports import find_unused_imports


def _get_unused_names(source: str) -> set[str]:
    """Get set of unused import names from source code."""
    return {imp.name for imp in find_unused_imports(source)}


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Shadowed by assignment
        pytest.param(
            'import re\n'
            're = "shadowed"\n',
            {'re'},
            id='shadowed by variable assignment',
        ),
        # Shadowed by function definition
        pytest.param(
            'import math\n'
            '\n'
            'def math():\n'
            '    return 42\n',
            {'math'},
            id='shadowed by function definition',
        ),
        # Shadowed by class definition
        pytest.param(
            'import abc\n'
            '\n'
            'class abc:\n'
            '    pass\n',
            {'abc'},
            id='shadowed by class definition',
        ),
        # Shadowed by for loop variable
        pytest.param(
            'import copy\n'
            'for copy in range(10):\n'
            '    pass\n',
            {'copy'},
            id='shadowed by for loop variable',
        ),
        # Shadowed by with statement target
        pytest.param(
            'import io\n'
            'with open(__file__) as io:\n'
            '    pass\n',
            {'io'},
            id='shadowed by with statement target',
        ),
        # Shadowed by except clause variable
        pytest.param(
            'import traceback\n'
            'try:\n'
            '    raise ValueError()\n'
            'except ValueError as traceback:\n'
            '    pass\n',
            {'traceback'},
            id='shadowed by except clause variable',
        ),
        # Shadowed by walrus operator
        pytest.param(
            'import itertools\n'
            'result = [itertools := x for x in range(5)]\n',
            {'itertools'},
            id='shadowed by walrus operator',
        ),
        # Shadowed in tuple unpacking
        pytest.param(
            'import os\n'
            'os, sys = 1, 2\n',
            {'os'},
            id='shadowed in tuple unpacking',
        ),
        # Shadowed in augmented assignment target
        pytest.param(
            'import count\n'
            'count = 0\n'
            'count += 1\n',
            {'count'},
            id='shadowed then augmented',
        ),
    ),
)
def test_shadowed_imports(s, expected):
    """Test that shadowed imports ARE flagged as unused."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    's',
    (
        # Used before being shadowed
        pytest.param(
            'import os\n'
            'x = os.getcwd()\n'
            'os = "shadowed"\n',
            id='used before shadowed',
        ),
        # Used in attribute before shadowing
        pytest.param(
            'import sys\n'
            'v = sys.version\n'
            'sys = None\n',
            id='used in attribute before shadowed',
        ),
    ),
)
def test_used_before_shadowed_noop(s):
    """Test that imports used before shadowing are NOT flagged."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    's',
    (
        # Function parameter shadowing - known limitation
        pytest.param(
            'from operator import add\n'
            '\n'
            'def process(add=None):\n'
            '    return add\n',
            id='function parameter shadowing - known limitation',
        ),
    ),
)
def test_function_parameter_shadowing_known_limitation(s):
    """Test known limitation: function parameter shadowing not detected.

    The linter doesn't do full scope analysis, so when a function parameter
    shadows an import and is used within the function, the linter incorrectly
    thinks the import is used. This is a false negative but acceptable for
    a simple linter without full scope analysis.
    """
    # This returns empty set (false negative) because 'add' is used in
    # 'return add', and the linter doesn't know it refers to the parameter
    assert _get_unused_names(s) == set()
