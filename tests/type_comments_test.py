"""Tests for PEP 484 type comment handling."""

from __future__ import annotations

import pytest

from import_analyzer import find_unused_imports


def _get_unused_names(source: str) -> set[str]:
    """Get set of unused import names from source code."""
    return {imp.name for imp in find_unused_imports(source)}


# =============================================================================
# Variable type comments (should NOT flag as unused)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import Optional\n"
            "x = None  # type: Optional[int]\n",
            id="simple variable type comment",
        ),
        pytest.param(
            "from typing import List\n"
            "items = []  # type: List[int]\n",
            id="list type comment",
        ),
        pytest.param(
            "from typing import Dict, List\n"
            "data = {}  # type: Dict[str, List[int]]\n",
            id="nested generic type comment",
        ),
        pytest.param(
            "from typing import Dict, List, Optional\n"
            "data = {}  # type: Dict[str, List[Optional[int]]]\n",
            id="deeply nested generic type comment",
        ),
        pytest.param(
            "import typing\n"
            "x = None  # type: typing.Optional[int]\n",
            id="qualified type in comment",
        ),
        pytest.param(
            "from typing import Tuple\n"
            "x, y = 1, 2  # type: Tuple[int, str]\n",
            id="tuple unpacking type comment",
        ),
        pytest.param(
            "from typing import Union\n"
            "x = None  # type: Union[int, str]\n",
            id="union type comment",
        ),
        pytest.param(
            "from typing import Callable\n"
            "f = None  # type: Callable[[int], str]\n",
            id="callable type comment",
        ),
    ),
)
def test_variable_type_comment_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# Function signature type comments (should NOT flag as unused)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "def foo(a, b):  # type: (int, str) -> bool\n"
            "    return True\n",
            id="basic function signature",
        ),
        pytest.param(
            "from typing import Optional\n"
            "def foo(a):  # type: (int) -> Optional[str]\n"
            "    return None\n",
            id="function with optional return",
        ),
        pytest.param(
            "from typing import List, Dict\n"
            "def foo(x):  # type: (Dict[str, int]) -> List[str]\n"
            "    return []\n",
            id="function with generic args and return",
        ),
        pytest.param(
            "def foo(*args):  # type: (...)\n"
            "    pass\n",
            id="function with ellipsis args",
        ),
        pytest.param(
            "def foo(*args, **kwargs):  # type: (*int, **str)\n"
            "    pass\n",
            id="function with starred type args",
        ),
        pytest.param(
            "from typing import List, Optional\n"
            "def foo(x):  # type: (List[Optional[int]]) -> Optional[List[str]]\n"
            "    return None\n",
            id="function with nested generics",
        ),
    ),
)
def test_function_signature_type_comment_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# Per-argument type comments (should NOT flag as unused)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import List\n"
            "def foo(\n"
            "    a,  # type: int\n"
            "    b,  # type: List[str]\n"
            "):\n"
            "    pass\n",
            id="per-argument type comments",
        ),
        pytest.param(
            "from typing import Optional\n"
            "def foo(\n"
            "    x,  # type: Optional[int]\n"
            "):\n"
            "    # type: (...)\n"
            "    pass\n",
            id="per-arg with body type comment",
        ),
    ),
)
def test_per_argument_type_comment_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# For loop type comments (should NOT flag as unused)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import List\n"
            "items = []  # type: List[int]\n"
            "for x in items:  # type: int\n"
            "    pass\n",
            id="for loop type comment",
        ),
        pytest.param(
            "from typing import Tuple, List\n"
            "pairs = []  # type: List[Tuple[int, str]]\n"
            "for x, y in pairs:  # type: Tuple[int, str]\n"
            "    pass\n",
            id="for loop tuple unpacking type comment",
        ),
    ),
)
def test_for_loop_type_comment_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# With statement type comments (should NOT flag as unused)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import TextIO\n"
            "with open('f') as fp:  # type: TextIO\n"
            "    pass\n",
            id="with statement type comment",
        ),
    ),
)
def test_with_statement_type_comment_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# Async variants (should NOT flag as unused)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import Optional\n"
            "async def foo(a):  # type: (int) -> Optional[str]\n"
            "    return None\n",
            id="async function type comment",
        ),
    ),
)
def test_async_type_comment_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# PEP 526 precedence over type comments
# =============================================================================


# Note: For variable annotations (AnnAssign), Python's AST parser rejects
# having both annotation AND type comment when type_comments=True.
# So we only test function cases where both can coexist.


@pytest.mark.parametrize(
    ("s", "expected"),
    (
        pytest.param(
            "from typing import Optional, List\n"
            "def foo(a: int) -> Optional[str]:  # type: (List[int]) -> str\n"
            "    return None\n",
            {"List"},
            id="function annotation takes precedence",
        ),
        pytest.param(
            "from typing import List, Dict\n"
            "def foo(\n"
            "    a: int,  # type: List[int]\n"
            "):\n"
            "    pass\n",
            {"List", "Dict"},
            id="per-arg annotation takes precedence",
        ),
    ),
)
def test_pep526_precedence(s, expected):
    assert _get_unused_names(s) == expected


# =============================================================================
# "type: ignore" is skipped (not a type annotation)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import List\n"
            "x = []  # type: ignore\n",
            id="type ignore on assignment",
        ),
        pytest.param(
            "from typing import Optional\n"
            "def foo(a):  # type: ignore\n"
            "    pass\n",
            id="type ignore on function",
        ),
        pytest.param(
            "from typing import Dict\n"
            "x = {}  # type: ignore[assignment]\n",
            id="type ignore with code",
        ),
    ),
)
def test_type_ignore_flags_unused(s):
    # "type: ignore" comments should NOT count as usage
    unused = _get_unused_names(s)
    assert len(unused) > 0  # The import should be flagged as unused


# =============================================================================
# Edge cases - syntax anomalies handled by AST
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import List\n"
            "x = 1; y = []  # type: List[int]\n",
            id="semicolon separated - type comment on last",
        ),
        pytest.param(
            "from typing import Optional\n"
            "x = \\\n"
            "    None  # type: Optional[int]\n",
            id="backslash continuation",
        ),
        pytest.param(
            "from typing import List\n"
            "x = []  # type: List[int]  # some other comment\n",
            id="type comment with trailing comment",
        ),
        pytest.param(
            "from typing import Dict\n"
            "x = {}  #type:Dict[str,int]\n",
            id="no spaces in type comment",
        ),
        pytest.param(
            "from typing import List\n"
            "x = []  #  type:   List[int]  \n",
            id="extra whitespace in type comment",
        ),
        pytest.param(
            "from typing import Optional\n"
            "x = None\t# type:\tOptional[int]\n",
            id="tabs in type comment",
        ),
    ),
)
def test_edge_cases_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# Invalid type comments (gracefully ignored)
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import List\n"
            "x = []  # type: List[\n",
            id="invalid type syntax - unclosed bracket",
        ),
        pytest.param(
            "from typing import Dict\n"
            "x = {}  # type: ???\n",
            id="invalid type syntax - invalid chars",
        ),
    ),
)
def test_invalid_type_comment_flags_unused(s):
    # Invalid type comments should not crash, and import should be unused
    unused = _get_unused_names(s)
    assert len(unused) > 0


# =============================================================================
# Nested functions and classes
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import Optional\n"
            "class Foo:\n"
            "    def bar(self, x):  # type: (int) -> Optional[str]\n"
            "        return None\n",
            id="method type comment",
        ),
        pytest.param(
            "from typing import List\n"
            "def outer():\n"
            "    def inner(x):  # type: (int) -> List[str]\n"
            "        return []\n"
            "    return inner\n",
            id="nested function type comment",
        ),
    ),
)
def test_nested_type_comment_noop(s):
    assert _get_unused_names(s) == set()


# =============================================================================
# Forward references in type comments
# =============================================================================


@pytest.mark.parametrize(
    "s",
    (
        pytest.param(
            "from typing import Optional\n"
            "x = None  # type: Optional['Foo']\n"
            "class Foo:\n"
            "    pass\n",
            id="forward reference in type comment",
        ),
    ),
)
def test_forward_reference_type_comment_noop(s):
    assert _get_unused_names(s) == set()
