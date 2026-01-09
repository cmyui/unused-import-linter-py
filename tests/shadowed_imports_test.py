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
    ('s', 'expected'),
    (
        # Function parameter shadowing
        pytest.param(
            'from operator import add\n'
            '\n'
            'def process(add=None):\n'
            '    return add\n',
            {'add'},
            id='function parameter shadowing',
        ),
        # Nested function parameter shadowing
        pytest.param(
            'from math import sqrt\n'
            '\n'
            'def outer():\n'
            '    def inner(sqrt):\n'
            '        return sqrt\n'
            '    return inner\n',
            {'sqrt'},
            id='nested function parameter shadowing',
        ),
        # Lambda parameter shadowing
        pytest.param(
            'from operator import mul\n'
            'f = lambda mul: mul * 2\n',
            {'mul'},
            id='lambda parameter shadowing',
        ),
        # For loop variable shadowing in function
        pytest.param(
            'from itertools import chain\n'
            '\n'
            'def process():\n'
            '    for chain in range(10):\n'
            '        print(chain)\n',
            {'chain'},
            id='for loop variable shadowing in function',
        ),
        # Local variable shadowing in function
        pytest.param(
            'from collections import Counter\n'
            '\n'
            'def process():\n'
            '    Counter = {}\n'
            '    return Counter\n',
            {'Counter'},
            id='local variable shadowing in function',
        ),
    ),
)
def test_function_scope_shadowing(s, expected):
    """Test that imports shadowed by function-local names ARE flagged as unused.

    With full scope analysis, the linter correctly detects when a name used
    inside a function refers to a local binding (parameter, loop variable, etc.)
    rather than the module-level import.
    """
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    's',
    (
        # Import used in function that doesn't shadow it
        pytest.param(
            'from operator import add\n'
            '\n'
            'def process(x, y):\n'
            '    return add(x, y)\n',
            id='import used in function body',
        ),
        # Import used in default argument
        pytest.param(
            'from operator import add\n'
            '\n'
            'def process(op=add):\n'
            '    return op(1, 2)\n',
            id='import used in default argument',
        ),
        # Import used in decorator
        pytest.param(
            'from functools import lru_cache\n'
            '\n'
            '@lru_cache\n'
            'def expensive(x):\n'
            '    return x * 2\n',
            id='import used in decorator',
        ),
        # Import used in nested function (closure)
        pytest.param(
            'from operator import add\n'
            '\n'
            'def outer():\n'
            '    def inner():\n'
            '        return add(1, 2)\n'
            '    return inner\n',
            id='import used in closure',
        ),
        # Import used in annotation
        pytest.param(
            'from typing import List\n'
            '\n'
            'def process(items: List[int]) -> List[str]:\n'
            '    return [str(x) for x in items]\n',
            id='import used in annotation',
        ),
    ),
)
def test_function_scope_usage_noop(s):
    """Test that imports used at function scope are NOT flagged."""
    assert _get_unused_names(s) == set()
