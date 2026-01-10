"""Tests for comprehensive scope analysis edge cases."""
from __future__ import annotations

import pytest

from remove_unused_imports import find_unused_imports


def _get_unused_names(source: str) -> set[str]:
    """Get set of unused import names from source code."""
    return {imp.name for imp in find_unused_imports(source)}


# =============================================================================
# Class scope quirk (class body doesn't enclose nested functions)
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Class-level variable shadowing import, method uses class var
        pytest.param(
            'import math\n'
            '\n'
            'class Calculator:\n'
            '    math = "not the module"\n'
            '    \n'
            '    def compute(self):\n'
            '        # This refers to the import, not the class var\n'
            '        return math.sqrt(4)\n',
            set(),  # import IS used (class scope doesn't enclose methods)
            id='class scope does not enclose methods',
        ),
        # Variable defined only in class body (not used in method)
        pytest.param(
            'import os\n'
            '\n'
            'class MyClass:\n'
            '    os = "shadowed"\n'
            '    x = os  # Uses class-level os\n',
            {'os'},  # import is shadowed in class body
            id='class body shadowing',
        ),
    ),
)
def test_class_scope_quirk(s, expected):
    """Test that class scope doesn't enclose nested functions."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Async constructs
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Async function with decorator
        pytest.param(
            'from functools import lru_cache\n'
            '\n'
            '@lru_cache\n'
            'async def fetch():\n'
            '    pass\n',
            id='async function with decorator',
        ),
        # Async for loop
        pytest.param(
            'import asyncio\n'
            '\n'
            'async def process():\n'
            '    async for item in asyncio.Queue():\n'
            '        pass\n',
            id='async for loop uses import',
        ),
        # Async with statement
        pytest.param(
            'import aiofiles\n'
            '\n'
            'async def read():\n'
            '    async with aiofiles.open("f") as f:\n'
            '        pass\n',
            id='async with uses import',
        ),
    ),
)
def test_async_constructs_noop(s):
    """Test that imports used in async constructs are NOT flagged."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Async for loop shadowing
        pytest.param(
            'import item\n'
            '\n'
            'async def process():\n'
            '    async for item in some_iter():\n'
            '        print(item)\n',
            {'item'},
            id='async for loop shadowing',
        ),
        # Async with shadowing
        pytest.param(
            'import f\n'
            '\n'
            'async def read():\n'
            '    async with open("x") as f:\n'
            '        print(f)\n',
            {'f'},
            id='async with target shadowing',
        ),
        # Async for with else
        pytest.param(
            'import done\n'
            '\n'
            'async def process():\n'
            '    async for item in some_iter():\n'
            '        pass\n'
            '    else:\n'
            '        done = True\n',
            {'done'},
            id='async for else shadowing',
        ),
    ),
)
def test_async_constructs_shadowing(s, expected):
    """Test that imports shadowed in async constructs ARE flagged."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Function parameters: positional-only, keyword-only, *args, **kwargs
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Positional-only parameter shadowing
        pytest.param(
            'from typing import pos\n'
            '\n'
            'def func(pos, /):\n'
            '    return pos\n',
            {'pos'},
            id='positional-only parameter shadowing',
        ),
        # Keyword-only parameter shadowing
        pytest.param(
            'from typing import kw\n'
            '\n'
            'def func(*, kw):\n'
            '    return kw\n',
            {'kw'},
            id='keyword-only parameter shadowing',
        ),
        # *args shadowing
        pytest.param(
            'import args\n'
            '\n'
            'def func(*args):\n'
            '    return args\n',
            {'args'},
            id='varargs shadowing',
        ),
        # **kwargs shadowing
        pytest.param(
            'import kwargs\n'
            '\n'
            'def func(**kwargs):\n'
            '    return kwargs\n',
            {'kwargs'},
            id='kwargs shadowing',
        ),
    ),
)
def test_function_parameter_variants(s, expected):
    """Test various function parameter types for shadowing."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Function annotations with keyword-only defaults
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # kw_default annotation
        pytest.param(
            'from typing import Optional\n'
            '\n'
            'def func(*, x: Optional[int] = None):\n'
            '    pass\n',
            id='keyword-only with default and annotation',
        ),
        # Multiple kw_defaults with some None
        pytest.param(
            'from typing import List\n'
            '\n'
            'def func(*, a, b: List[int] = []):\n'
            '    pass\n',
            id='mixed keyword-only defaults',
        ),
    ),
)
def test_kw_defaults_noop(s):
    """Test imports used in keyword-only defaults are NOT flagged."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Starred unpacking in assignments
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        pytest.param(
            'import rest\n'
            'first, *rest = [1, 2, 3]\n',
            {'rest'},
            id='starred unpacking shadowing',
        ),
        pytest.param(
            'import middle\n'
            'first, *middle, last = [1, 2, 3, 4]\n',
            {'middle'},
            id='middle starred unpacking',
        ),
    ),
)
def test_starred_unpacking(s, expected):
    """Test starred unpacking creates bindings."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Match statements (Python 3.10+)
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Simple match-as pattern
        pytest.param(
            'import x\n'
            '\n'
            'match value:\n'
            '    case x:\n'
            '        print(x)\n',
            {'x'},
            id='match as pattern shadowing',
        ),
        # Match-as with nested pattern
        pytest.param(
            'import point\n'
            '\n'
            'match value:\n'
            '    case (a, b) as point:\n'
            '        print(point)\n',
            {'point'},
            id='match as with nested pattern',
        ),
        # Match star pattern
        pytest.param(
            'import rest\n'
            '\n'
            'match value:\n'
            '    case [first, *rest]:\n'
            '        print(rest)\n',
            {'rest'},
            id='match star pattern',
        ),
        # Match mapping with rest
        pytest.param(
            'import extra\n'
            '\n'
            'match value:\n'
            '    case {"key": val, **extra}:\n'
            '        print(extra)\n',
            {'extra'},
            id='match mapping rest',
        ),
        # Match sequence pattern
        pytest.param(
            'import a\n'
            'import b\n'
            '\n'
            'match value:\n'
            '    case [a, b]:\n'
            '        print(a, b)\n',
            {'a', 'b'},
            id='match sequence pattern',
        ),
        # Match class pattern
        pytest.param(
            'import x\n'
            'import y\n'
            '\n'
            'match value:\n'
            '    case Point(x, y=y):\n'
            '        print(x, y)\n',
            {'x', 'y'},
            id='match class pattern',
        ),
        # Match or pattern
        pytest.param(
            'import x\n'
            '\n'
            'match value:\n'
            '    case 1 | 2 | x:\n'
            '        print(x)\n',
            {'x'},
            id='match or pattern',
        ),
        # Match with guard
        pytest.param(
            'import math\n'
            '\n'
            'match value:\n'
            '    case x if math.isnan(x):\n'
            '        print(x)\n',
            set(),  # math is used in guard
            id='match with guard uses import',
        ),
    ),
)
def test_match_patterns(s, expected):
    """Test match statement pattern bindings."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Comprehensions: all types and edge cases
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Set comprehension shadowing
        pytest.param(
            'import x\n'
            'result = {x for x in range(10)}\n',
            {'x'},
            id='set comprehension shadowing',
        ),
        # Dict comprehension shadowing
        pytest.param(
            'import k\n'
            'import v\n'
            'result = {k: v for k, v in items}\n',
            {'k', 'v'},
            id='dict comprehension shadowing',
        ),
        # Generator expression shadowing
        pytest.param(
            'import x\n'
            'result = (x for x in range(10))\n',
            {'x'},
            id='generator expression shadowing',
        ),
        # Multiple generators
        pytest.param(
            'import x\n'
            'import y\n'
            'result = [x + y for x in range(5) for y in range(5)]\n',
            {'x', 'y'},
            id='multiple generators shadowing',
        ),
        # Comprehension with if clause
        pytest.param(
            'import math\n'
            'result = [x for x in range(10) if math.sqrt(x) > 2]\n',
            set(),  # math is used in filter
            id='comprehension filter uses import',
        ),
    ),
)
def test_comprehension_variants(s, expected):
    """Test various comprehension types."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Walrus operator in comprehensions (leaks to enclosing scope)
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        pytest.param(
            'import last\n'
            'result = [last := x for x in range(10)]\n',
            {'last'},
            id='walrus in list comp shadows import',
        ),
        pytest.param(
            'import seen\n'
            'result = {x for x in range(10) if (seen := x) > 0}\n',
            {'seen'},
            id='walrus in set comp filter shadows import',
        ),
    ),
)
def test_walrus_in_comprehension(s, expected):
    """Test walrus operator binding leaks out of comprehension."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Attribute access edge cases
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Non-load context (store to attribute)
        pytest.param(
            'import obj\n'
            'obj.attr = 1\n',
            id='attribute store uses import',
        ),
        # Chained attribute access
        pytest.param(
            'import a\n'
            'x = a.b.c.d\n',
            id='chained attribute access',
        ),
    ),
)
def test_attribute_access_noop(s):
    """Test attribute access patterns."""
    assert _get_unused_names(s) == set()


# =============================================================================
# For loop with else clause
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        pytest.param(
            'import found\n'
            'for item in items:\n'
            '    if condition:\n'
            '        break\n'
            'else:\n'
            '    found = False\n',
            {'found'},
            id='for else clause shadowing',
        ),
    ),
)
def test_for_else_shadowing(s, expected):
    """Test for-else clause creates bindings."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    's',
    (
        pytest.param(
            'import handler\n'
            'for item in items:\n'
            '    pass\n'
            'else:\n'
            '    handler()\n',
            id='for else uses import',
        ),
    ),
)
def test_for_else_usage_noop(s):
    """Test imports used in for-else are NOT flagged."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Global/Nonlocal declarations
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Global declaration
        pytest.param(
            'import counter\n'
            '\n'
            'def increment():\n'
            '    global counter\n'
            '    counter += 1\n',
            id='global declaration uses import',
        ),
    ),
)
def test_global_declaration_noop(s):
    """Test global declarations resolve to module scope."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    's',
    (
        # Nonlocal in nested function
        pytest.param(
            'import value\n'
            '\n'
            'def outer():\n'
            '    value = 0\n'
            '    def inner():\n'
            '        nonlocal value\n'
            '        value += 1\n'
            '    inner()\n',
            id='nonlocal uses enclosing scope',
        ),
    ),
)
def test_nonlocal_declaration(s):
    """Test nonlocal declarations resolve to enclosing scope."""
    # The import is shadowed by outer's local variable
    assert _get_unused_names(s) == {'value'}


# =============================================================================
# Exception handler bindings
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        pytest.param(
            'import e\n'
            'try:\n'
            '    raise ValueError()\n'
            'except ValueError as e:\n'
            '    print(e)\n',
            {'e'},
            id='except handler shadows import',
        ),
    ),
)
def test_except_handler_shadowing(s, expected):
    """Test exception handler 'as' variable creates binding."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    's',
    (
        pytest.param(
            'import traceback\n'
            'try:\n'
            '    raise ValueError()\n'
            'except ValueError:\n'
            '    traceback.print_exc()\n',
            id='except handler body uses import',
        ),
    ),
)
def test_except_handler_usage_noop(s):
    """Test imports used in except handlers are NOT flagged."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Class keywords (metaclass, etc.)
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        pytest.param(
            'from abc import ABCMeta\n'
            '\n'
            'class MyClass(metaclass=ABCMeta):\n'
            '    pass\n',
            id='metaclass keyword uses import',
        ),
    ),
)
def test_class_keywords_noop(s):
    """Test class keyword arguments use imports."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Module-level assignment shadowing
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        pytest.param(
            'import x\n'
            'x = 1\n',
            {'x'},
            id='module level assignment shadows import',
        ),
        pytest.param(
            'from typing import List\n'
            'List = str\n',
            {'List'},
            id='module level assignment shadows from-import',
        ),
    ),
)
def test_module_level_shadowing(s, expected):
    """Test module-level assignments shadow imports."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Class decorators
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        pytest.param(
            'from dataclasses import dataclass\n'
            '\n'
            '@dataclass\n'
            'class MyClass:\n'
            '    x: int\n',
            id='class decorator uses import',
        ),
    ),
)
def test_class_decorator_noop(s):
    """Test class decorators use imports."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Augmented assignment
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        pytest.param(
            'import counter\n'
            'counter += 1\n',
            id='augmented assign uses import',
        ),
        pytest.param(
            'import obj\n'
            'obj.attr += 1\n',
            id='augmented assign on attribute uses import',
        ),
        pytest.param(
            'import obj\n'
            'obj.attr: int = 1\n',
            id='annotated assign on attribute uses import',
        ),
    ),
)
def test_assignment_variants_noop(s):
    """Test various assignment forms use imports."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Comprehension with multiple generators and if clauses
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        pytest.param(
            'import math\n'
            'result = [x for x in range(10) for y in range(10) if math.sqrt(y) > 1]\n',
            id='nested generator if clause uses import',
        ),
    ),
)
def test_comprehension_nested_if_noop(s):
    """Test nested comprehension if clauses use imports."""
    assert _get_unused_names(s) == set()
