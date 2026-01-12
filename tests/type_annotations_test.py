"""Tests for type annotation handling (direct and forward references)."""
from __future__ import annotations

import pytest

from import_analyzer import find_unused_imports


def _get_unused_names(source: str) -> set[str]:
    """Get set of unused import names from source code."""
    return {imp.name for imp in find_unused_imports(source)}


# =============================================================================
# Direct type annotations
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Return annotation
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def func() -> Path:\n'
            '    pass\n',
            id='return annotation',
        ),
        # Parameter annotation
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def func(p: Path) -> None:\n'
            '    pass\n',
            id='parameter annotation',
        ),
        # Variable annotation
        pytest.param(
            'from pathlib import Path\n'
            'my_path: Path\n',
            id='variable annotation',
        ),
        # Annotated assignment
        pytest.param(
            'from pathlib import Path\n'
            'my_path: Path = Path(".")\n',
            id='annotated assignment',
        ),
        # Class variable annotation
        pytest.param(
            'from typing import List\n'
            '\n'
            'class MyClass:\n'
            '    items: List[int]\n',
            id='class variable annotation',
        ),
        # Generic annotation
        pytest.param(
            'from typing import List, Optional\n'
            '\n'
            'def func(items: List[int]) -> Optional[str]:\n'
            '    pass\n',
            id='generic type annotations',
        ),
        # Nested generic annotation
        pytest.param(
            'from typing import Dict, List, Optional\n'
            '\n'
            'def func() -> Dict[str, List[Optional[int]]]:\n'
            '    pass\n',
            id='nested generic annotations',
        ),
        # *args annotation
        pytest.param(
            'from typing import Any\n'
            '\n'
            'def func(*args: Any) -> None:\n'
            '    pass\n',
            id='varargs annotation',
        ),
        # **kwargs annotation
        pytest.param(
            'from typing import Any\n'
            '\n'
            'def func(**kwargs: Any) -> None:\n'
            '    pass\n',
            id='kwargs annotation',
        ),
        # Async function annotation
        pytest.param(
            'from typing import Optional\n'
            '\n'
            'async def func() -> Optional[int]:\n'
            '    pass\n',
            id='async function annotation',
        ),
    ),
)
def test_direct_annotations_noop(s):
    """Test that imports used in direct type annotations are NOT flagged."""
    assert _get_unused_names(s) == set()


# =============================================================================
# String annotations (forward references)
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # String return annotation
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def func() -> "Path":\n'
            '    pass\n',
            id='string return annotation',
        ),
        # String parameter annotation
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def func(p: "Path") -> None:\n'
            '    pass\n',
            id='string parameter annotation',
        ),
        # String annotation with subscript
        pytest.param(
            'from typing import List\n'
            '\n'
            'def func() -> "List[int]":\n'
            '    pass\n',
            id='string annotation with subscript',
        ),
        # Nested string annotation
        pytest.param(
            'from typing import Optional\n'
            'from pathlib import Path\n'
            '\n'
            'def func() -> "Optional[Path]":\n'
            '    pass\n',
            id='nested string annotation',
        ),
        # Class forward reference to self
        pytest.param(
            'class Node:\n'
            '    def add_child(self, child: "Node") -> None:\n'
            '        pass\n',
            id='class forward reference to self',
        ),
        # Multiple forward references
        pytest.param(
            'from typing import Dict\n'
            'from pathlib import Path\n'
            '\n'
            'def func() -> "Dict[str, Path]":\n'
            '    pass\n',
            id='multiple types in forward reference',
        ),
        # String annotation in variable
        pytest.param(
            'from pathlib import Path\n'
            'my_path: "Path"\n',
            id='string variable annotation',
        ),
    ),
)
def test_string_annotations_noop(s):
    """Test that imports used in string annotations are NOT flagged."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Mixed annotations
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Some used in annotations, some not
        pytest.param(
            'from typing import List, Dict, Optional, Tuple\n'
            '\n'
            'def func(x: Optional[int]) -> List[str]:\n'
            '    pass\n',
            {'Dict', 'Tuple'},
            id='partial annotation usage',
        ),
        # Used in string annotation but not others
        pytest.param(
            'from typing import List, Dict\n'
            'from pathlib import Path\n'
            '\n'
            'def func() -> "Path":\n'
            '    pass\n',
            {'List', 'Dict'},
            id='only string annotation used',
        ),
    ),
)
def test_annotation_partial_usage(s, expected):
    """Test that unused annotation imports ARE flagged."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Edge cases
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Quoted type in Optional
        pytest.param(
            'from typing import Optional\n'
            'from pathlib import Path\n'
            '\n'
            'x: Optional["Path"] = None\n',
            id='quoted type inside Optional',
        ),
        # Quoted type in Union
        pytest.param(
            'from typing import Union\n'
            'from pathlib import Path\n'
            '\n'
            'x: Union[str, "Path"] = ""\n',
            id='quoted type inside Union',
        ),
    ),
)
def test_quoted_types_in_generics_noop(s):
    """Test that quoted types inside generics are properly detected."""
    unused = _get_unused_names(s)
    assert 'Path' not in unused


@pytest.mark.parametrize(
    's',
    (
        # String annotation with attribute access
        pytest.param(
            'import typing\n'
            '\n'
            'x: "typing.Optional[int]" = None\n',
            id='string annotation with attribute access',
        ),
    ),
)
def test_string_annotation_attribute_access_noop(s):
    """Test string annotations with attribute access use imports."""
    assert _get_unused_names(s) == set()


# =============================================================================
# String literals that are NOT annotations
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # String literal in assignment is not an annotation
        pytest.param(
            'x = "health"; import health\n',
            {'health'},
            id='string literal in assignment',
        ),
        # String literal in function call is not an annotation
        pytest.param(
            'print("os"); import os\n',
            {'os'},
            id='string literal in function call',
        ),
        # String literal in list is not an annotation
        pytest.param(
            'x = ["json"]; import json\n',
            {'json'},
            id='string literal in list',
        ),
        # String literal in dict is not an annotation
        pytest.param(
            'x = {"key": "sys"}; import sys\n',
            {'sys'},
            id='string literal in dict',
        ),
    ),
)
def test_string_literal_not_annotation(s, expected):
    """Test that string literals outside annotation contexts don't count as usage."""
    assert _get_unused_names(s) == expected


# =============================================================================
# typing.cast() - first argument is annotation context
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # cast with direct type
        pytest.param(
            'from typing import cast, Optional\n'
            '\n'
            'x = cast(Optional[int], None)\n',
            id='cast with direct type',
        ),
        # cast with string type
        pytest.param(
            'from typing import cast, Optional\n'
            '\n'
            'x = cast("Optional[int]", None)\n',
            id='cast with string type',
        ),
        # cast with imported type
        pytest.param(
            'from typing import cast\n'
            'from pathlib import Path\n'
            '\n'
            'x = cast(Path, "./file")\n',
            id='cast with imported type',
        ),
        # cast with forward reference
        pytest.param(
            'from typing import cast\n'
            'from pathlib import Path\n'
            '\n'
            'x = cast("Path", "./file")\n',
            id='cast with forward reference',
        ),
    ),
)
def test_typing_cast_noop(s):
    """Test that types used in typing.cast() are NOT flagged."""
    assert _get_unused_names(s) == set()


# =============================================================================
# TypeVar - constraints and bound are annotation contexts
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # TypeVar with direct bound
        pytest.param(
            'from typing import TypeVar, List\n'
            '\n'
            'T = TypeVar("T", bound=List)\n',
            id='TypeVar with direct bound',
        ),
        # TypeVar with string bound
        pytest.param(
            'from typing import TypeVar, List\n'
            '\n'
            'T = TypeVar("T", bound="List")\n',
            id='TypeVar with string bound',
        ),
        # TypeVar with direct constraints
        pytest.param(
            'from typing import TypeVar\n'
            '\n'
            'T = TypeVar("T", int, str)\n',
            id='TypeVar with direct constraints',
        ),
        # TypeVar with string constraints
        pytest.param(
            'from typing import TypeVar, List, Dict\n'
            '\n'
            'T = TypeVar("T", "List", "Dict")\n',
            id='TypeVar with string constraints',
        ),
        # TypeVar with mixed constraints
        pytest.param(
            'from typing import TypeVar, List\n'
            '\n'
            'T = TypeVar("T", int, "List")\n',
            id='TypeVar with mixed constraints',
        ),
    ),
)
def test_typevar_noop(s):
    """Test that types used in TypeVar constraints/bound are NOT flagged."""
    assert _get_unused_names(s) == set()


# =============================================================================
# typing.Literal - contents are NOT annotation context
# =============================================================================


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Literal with string that looks like type
        pytest.param(
            'from typing import Literal\n'
            'from pathlib import Path\n'
            '\n'
            'def f(x: Literal["Path"]) -> None:\n'
            '    pass\n',
            {'Path'},
            id='Literal string is NOT type reference',
        ),
        # Literal with multiple strings
        pytest.param(
            'from typing import Literal\n'
            'from typing import Optional\n'
            '\n'
            'def f(x: Literal["Optional", "None"]) -> None:\n'
            '    pass\n',
            {'Optional'},
            id='Literal strings are NOT type references',
        ),
    ),
)
def test_literal_contents_not_annotation(s, expected):
    """Test that strings inside Literal[] are NOT treated as type annotations."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    's',
    (
        # Literal is itself used
        pytest.param(
            'from typing import Literal\n'
            '\n'
            'def f(x: Literal[1, 2, 3]) -> None:\n'
            '    pass\n',
            id='Literal type itself is used',
        ),
    ),
)
def test_literal_type_used_noop(s):
    """Test that Literal type itself is counted as used."""
    assert _get_unused_names(s) == set()


# =============================================================================
# typing.Annotated - first arg is annotation, rest are metadata
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Annotated with direct type
        pytest.param(
            'from typing import Annotated\n'
            'from pathlib import Path\n'
            '\n'
            'def f(x: Annotated[Path, "metadata"]) -> None:\n'
            '    pass\n',
            id='Annotated with direct type',
        ),
        # Annotated with string type
        pytest.param(
            'from typing import Annotated\n'
            'from pathlib import Path\n'
            '\n'
            'def f(x: Annotated["Path", "metadata"]) -> None:\n'
            '    pass\n',
            id='Annotated with string type',
        ),
    ),
)
def test_annotated_first_arg_noop(s):
    """Test that first argument of Annotated[] is treated as annotation."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Annotated metadata that looks like type should be flagged
        pytest.param(
            'from typing import Annotated\n'
            'from pathlib import Path\n'
            'from typing import Optional\n'
            '\n'
            'def f(x: Annotated[Path, "Optional"]) -> None:\n'
            '    pass\n',
            {'Optional'},
            id='Annotated metadata string NOT type reference',
        ),
    ),
)
def test_annotated_metadata_not_annotation(s, expected):
    """Test that metadata args in Annotated[] are NOT treated as type annotations."""
    assert _get_unused_names(s) == expected


# =============================================================================
# Partially quoted annotations (quotes inside non-quoted context)
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Quoted type inside Optional
        pytest.param(
            'from typing import Optional\n'
            'from queue import Queue\n'
            '\n'
            'def f() -> Optional["Queue[str]"]:\n'
            '    return None\n',
            id='quoted Queue inside Optional',
        ),
        # Quoted type inside Callable
        pytest.param(
            'from typing import Callable\n'
            'from queue import Queue\n'
            '\n'
            'Func = Callable[["Queue[str]"], None]\n',
            id='quoted Queue inside Callable',
        ),
    ),
)
def test_partially_quoted_annotation_noop(s):
    """Test that partially quoted types inside generics are properly detected."""
    assert _get_unused_names(s) == set()


# =============================================================================
# TypeAlias - RHS is annotation context when annotated with TypeAlias
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # TypeAlias with direct type
        pytest.param(
            'from typing import TypeAlias\n'
            'from pathlib import Path\n'
            '\n'
            'PathAlias: TypeAlias = Path\n',
            id='TypeAlias with direct type',
        ),
        # TypeAlias with string type
        pytest.param(
            'from typing import TypeAlias\n'
            'from pathlib import Path\n'
            '\n'
            'PathAlias: TypeAlias = "Path"\n',
            id='TypeAlias with string type',
        ),
    ),
)
def test_typealias_noop(s):
    """Test that RHS of TypeAlias annotation is treated as type context."""
    assert _get_unused_names(s) == set()


# =============================================================================
# Edge cases: whitespace, line continuations, semicolons, mixed types
# =============================================================================


@pytest.mark.parametrize(
    's',
    (
        # Extra whitespace in annotation
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def f(x:   Path  ) -> None:\n'
            '    pass\n',
            id='extra spaces in annotation',
        ),
        # Tabs in annotation
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def f(x:\tPath) -> None:\n'
            '    pass\n',
            id='tab in annotation',
        ),
        # Trailing whitespace in string annotation (leading causes IndentationError)
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def f(x: "Path  ") -> None:\n'
            '    pass\n',
            id='trailing spaces in string annotation',
        ),
        # Newline in multiline string annotation
        pytest.param(
            'from typing import Dict\n'
            'from pathlib import Path\n'
            '\n'
            'x: """Dict[\n'
            '    str,\n'
            '    Path\n'
            ']""" = {}\n',
            id='multiline string annotation',
        ),
    ),
)
def test_whitespace_variations_noop(s):
    """Test that various whitespace patterns are handled correctly."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    's',
    (
        # Backslash continuation in import
        pytest.param(
            'from pathlib \\\n'
            '    import Path\n'
            '\n'
            'x: Path\n',
            id='backslash in import',
        ),
        # Backslash continuation in annotation expression
        pytest.param(
            'from typing import Optional\n'
            'from pathlib import Path\n'
            '\n'
            'x: Optional[\\\n'
            '    Path\\\n'
            '] = None\n',
            id='backslash in annotation',
        ),
        # Backslash continuation in function signature
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def f(\\\n'
            '    x: Path\\\n'
            ') -> None:\n'
            '    pass\n',
            id='backslash in function signature',
        ),
    ),
)
def test_backslash_continuation_noop(s):
    """Test that backslash line continuations are handled correctly."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    's',
    (
        # Semicolon with annotation on same line
        pytest.param(
            'from pathlib import Path; x: Path = Path(".")\n',
            id='semicolon before annotation',
        ),
        # Multiple annotations on same line
        pytest.param(
            'from pathlib import Path\n'
            'x: Path; y: Path\n',
            id='multiple annotations same line',
        ),
        # Import and usage on same line
        pytest.param(
            'from pathlib import Path; p: Path = Path(".")\n',
            id='import and annotation same line',
        ),
    ),
)
def test_semicolon_statements_noop(s):
    """Test that semicolon-separated statements are handled correctly."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    's',
    (
        # Mixed direct and string in Union
        pytest.param(
            'from typing import Union\n'
            'from pathlib import Path\n'
            '\n'
            'x: Union[str, "Path"] = ""\n',
            id='Union with mixed direct and string',
        ),
        # Mixed direct and string in Optional
        pytest.param(
            'from typing import Optional\n'
            'from pathlib import Path\n'
            '\n'
            'x: Optional["Path"] = None\n',
            id='Optional with string type',
        ),
        # Nested mixed - string inside direct generic
        pytest.param(
            'from typing import List, Optional\n'
            'from pathlib import Path\n'
            '\n'
            'x: List[Optional["Path"]] = []\n',
            id='nested string in direct generic',
        ),
        # Multiple string refs in same annotation
        pytest.param(
            'from typing import Dict\n'
            'from pathlib import Path\n'
            'from io import StringIO\n'
            '\n'
            'x: "Dict[Path, StringIO]" = {}\n',
            id='multiple types in single string annotation',
        ),
        # Mixed: some in string, some direct
        pytest.param(
            'from typing import Tuple\n'
            'from pathlib import Path\n'
            'from io import StringIO\n'
            '\n'
            'x: Tuple["Path", StringIO, "Path"] = (Path("."), StringIO(), Path("."))\n',
            id='mixed string and direct in Tuple',
        ),
    ),
)
def test_mixed_forward_refs_noop(s):
    """Test that mixed forward references and direct types work correctly."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    's',
    (
        # cast with extra whitespace
        pytest.param(
            'from typing import cast\n'
            'from pathlib import Path\n'
            '\n'
            'x = cast(  "Path"  , None)\n',
            id='cast with extra whitespace',
        ),
        # cast with line continuation
        pytest.param(
            'from typing import cast\n'
            'from pathlib import Path\n'
            '\n'
            'x = cast(\\\n'
            '    "Path",\\\n'
            '    None)\n',
            id='cast with backslash continuation',
        ),
        # TypeVar with extra whitespace
        pytest.param(
            'from typing import TypeVar, List\n'
            '\n'
            'T = TypeVar(  "T"  ,   bound = "List"  )\n',
            id='TypeVar with extra whitespace',
        ),
        # TypeVar with line continuation
        pytest.param(
            'from typing import TypeVar, List, Dict\n'
            '\n'
            'T = TypeVar(\\\n'
            '    "T",\\\n'
            '    "List",\\\n'
            '    "Dict"\\\n'
            ')\n',
            id='TypeVar with backslash continuation',
        ),
        # Literal with semicolon nearby
        pytest.param(
            'from typing import Literal\n'
            'x: Literal["a"]; y: Literal["b"]\n',
            id='Literal with semicolons',
        ),
        # Annotated with complex whitespace
        pytest.param(
            'from typing import Annotated\n'
            'from pathlib import Path\n'
            '\n'
            'x: Annotated[  "Path"  ,  "metadata"  ] = Path(".")\n',
            id='Annotated with extra whitespace',
        ),
    ),
)
def test_typing_constructs_edge_cases_noop(s):
    """Test typing constructs with edge case formatting."""
    assert _get_unused_names(s) == set()


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Literal with whitespace - still should flag unused import
        pytest.param(
            'from typing import Literal\n'
            'from pathlib import Path\n'
            '\n'
            'x: Literal[  "Path"  ] = "Path"\n',
            {'Path'},
            id='Literal with whitespace still not type ref',
        ),
        # Annotated metadata with whitespace - still should flag
        pytest.param(
            'from typing import Annotated\n'
            'from pathlib import Path\n'
            'from typing import Optional\n'
            '\n'
            'x: Annotated[  Path  ,  "Optional"  ] = Path(".")\n',
            {'Optional'},
            id='Annotated metadata with whitespace still not type ref',
        ),
        # Leading whitespace in string annotation causes IndentationError when parsing
        # This matches pyflakes behavior (ForwardAnnotationSyntaxError)
        pytest.param(
            'from pathlib import Path\n'
            '\n'
            'def f(x: "  Path") -> None:\n'
            '    pass\n',
            {'Path'},
            id='leading spaces in string annotation unparseable',
        ),
    ),
)
def test_edge_cases_still_flag_unused(s, expected):
    """Test that edge case formatting doesn't break detection of truly unused imports."""
    assert _get_unused_names(s) == expected
