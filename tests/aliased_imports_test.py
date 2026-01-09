"""Tests for aliased import handling."""
from __future__ import annotations

import pytest

from remove_unused_imports import find_unused_imports


def _get_unused_names(source: str) -> set[str]:
    """Get set of unused import names from source code."""
    return {imp.name for imp in find_unused_imports(source)}


@pytest.mark.parametrize(
    's',
    (
        # Aliased import used
        pytest.param(
            'import numpy as np\n'
            'x = np.array([1, 2, 3])\n',
            id='aliased import used',
        ),
        # Aliased from-import used
        pytest.param(
            'from datetime import datetime as dt\n'
            'x = dt.now()\n',
            id='aliased from-import used',
        ),
        # Multiple aliased imports partial usage
        pytest.param(
            'from itertools import chain as ch, cycle as cy\n'
            'x = list(ch([1], [2]))\n',
            id='one of multiple aliased imports used',
        ),
    ),
)
def test_aliased_imports_noop(s):
    """Test that used aliased imports are NOT flagged."""
    assert 'np' not in _get_unused_names(s)
    assert 'dt' not in _get_unused_names(s)
    assert 'ch' not in _get_unused_names(s)


@pytest.mark.parametrize(
    ('s', 'expected'),
    (
        # Unused aliased import
        pytest.param(
            'import numpy as np\n',
            {'np'},
            id='unused aliased import',
        ),
        # Unused aliased from-import
        pytest.param(
            'from datetime import datetime as dt\n',
            {'dt'},
            id='unused aliased from-import',
        ),
        # Multiple unused aliased from-imports
        pytest.param(
            'from itertools import chain as ch, cycle as cy\n',
            {'ch', 'cy'},
            id='multiple unused aliased from-imports',
        ),
        # Partial aliased usage
        pytest.param(
            'from itertools import chain as ch, cycle as cy, repeat as rp\n'
            'x = list(ch([1], [2]))\n',
            {'cy', 'rp'},
            id='partial aliased usage',
        ),
        # Same name different modules
        pytest.param(
            'from os import path\n'
            'from sys import path as sys_path\n'
            'x = path.join("a", "b")\n',
            {'sys_path'},
            id='same name different modules aliased',
        ),
    ),
)
def test_aliased_imports(s, expected):
    """Test that unused aliased imports ARE flagged."""
    assert _get_unused_names(s) == expected


@pytest.mark.parametrize(
    ('s', 'name', 'module', 'original_name'),
    (
        # Regular import alias tracking
        pytest.param(
            'import numpy as np\n',
            'np',
            '',
            'numpy',
            id='import with alias tracks original',
        ),
        # From-import alias tracking
        pytest.param(
            'from datetime import datetime as dt\n',
            'dt',
            'datetime',
            'datetime',
            id='from-import with alias tracks module',
        ),
    ),
)
def test_aliased_import_metadata(s, name, module, original_name):
    """Test that aliased imports track correct metadata."""
    unused = find_unused_imports(s)
    assert len(unused) == 1
    imp = unused[0]
    assert imp.name == name
    assert imp.module == module
    assert imp.original_name == original_name
