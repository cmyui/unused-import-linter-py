"""Tests for type annotation handling (direct and forward references)."""
from __future__ import annotations

import pytest

from remove_unused_imports import find_unused_imports


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
