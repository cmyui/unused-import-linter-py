# import-analyzer-py

[![build status](https://github.com/cmyui/import-analyzer-py/actions/workflows/ci.yml/badge.svg)](https://github.com/cmyui/import-analyzer-py/actions/workflows/ci.yml)

A Python import analyzer with cross-file analysis, unused import detection, circular import warnings, and autofix.

## Comparison with Other Tools

| Feature                       | This tool | [Ruff]  | [Autoflake] | [Pyflakes] | [Pylint] | [Unimport] |
| ----------------------------- | :-------: | :-----: | :---------: | :--------: | :------: | :--------: |
| Detect unused imports         |    ✅     |   ✅    |     ✅      |     ✅     |    ✅    |     ✅     |
| Autofix                       |    ✅     |   ✅    |     ✅      |     ❌     |    ❌    |     ✅     |
| **Cross-file analysis**       |    ✅     |   ❌    |     ❌      |     ❌     |    ❌    |     ❌     |
| **Re-export tracking**        |    ✅     |   ❌¹   |     ❌      |     ❌     |   ❌²    |     ❌     |
| **Cascade detection**         |    ✅     |   ❌    |     ❌      |     ❌     |    ❌    |     ❌     |
| **Circular import warnings**  |    ✅     |   ❌    |     ❌      |     ❌     |    ❌    |     ❌     |
| **Unreachable file warnings** |    ✅     |   ❌    |     ❌      |     ❌     |    ❌    |     ❌     |
| Respects `__all__`            |    ✅     |   ✅    |     ⚠️³     |     ✅     |    ✅    |     ✅     |
| noqa: F401 support            |    ✅     |   ✅    |     ✅      |    ❌⁴     |   ✅⁵    |     ✅     |
| Full scope analysis (LEGB)    |    ✅     |   ✅    |     ⚠️⁶     |    ⚠️⁶     |    ✅    |     ✅     |
| String annotations            |    ✅     |   ✅    |     ✅      |     ✅     |    ✅    |     ✅     |
| TYPE_CHECKING blocks          |    ✅     |   ✅    |     ✅      |    ⚠️⁷     |    ✅    |     ✅     |
| Type comments (`# type:`)     |    ❌     |   ✅    |     ✅      |     ✅     |    ✅    |     ✅     |
| Redundant alias (`x as x`)    |    ❌     |   ✅    |     ❌      |     ❌     |    ❌    |     ❌     |
| Star import suggestions       |    ❌     |   ❌    |     ❌      |     ❌     |    ❌    |     ✅     |
| Redefinition warnings         |    ❌     |   ✅    |     ❌      |     ✅     |    ✅    |     ❌     |
| Speed                         | Moderate  | 🚀 Fast |  Moderate   |    Fast    |   Slow   |  Moderate  |

<sup>¹ Ruff suggests `import X as X` for `__init__.py` but doesn't track actual cross-file usage</sup><br>
<sup>² Pylint skips `__init__.py` by default but doesn't track actual re-export consumers</sup><br>
<sup>³ Autoflake only uses `__all__` to skip star import expansion, not to preserve re-exports</sup><br>
<sup>⁴ Pyflakes has no noqa support; Flake8 adds it as a wrapper layer</sup><br>
<sup>⁵ Pylint uses `# pylint: disable=unused-import`</sup><br>
<sup>⁶ Autoflake/Pyflakes have basic scope analysis but miss some LEGB edge cases</sup><br>
<sup>⁷ Pyflakes treats TYPE_CHECKING as normal conditional code (works but not explicit)</sup>

### What makes this tool unique

**Cross-file analysis** — This is the only tool that follows imports from your entry point and tracks which imports are actually used by other files. This enables:

- **Re-export preservation**: If `utils.py` imports `List` and `main.py` does `from utils import List`, the import in `utils.py` is correctly identified as used
- **Cascade detection**: When removing an unused import makes another import unused, this tool finds all of them in a single pass (note: imports in `__all__` are always preserved as public API)
- **Circular import detection**: Warns about import cycles in your codebase
- **Unreachable file detection**: Identifies files that become dead code after fixing imports

### Features we don't have (yet)

Based on analysis of other tools' source code:

- **Type comments**: `# type: int` style annotations (PEP 484) are not parsed
- **Redundant alias detection**: `import X as X` as explicit re-export marker (Ruff feature)
- **Star import suggestions**: Suggesting specific names to replace `from x import *` (Unimport feature)
- **Redefinition warnings**: Warning when an import is reassigned before use (Pyflakes feature)

[Ruff]: https://docs.astral.sh/ruff/rules/unused-import/
[Autoflake]: https://github.com/PyCQA/autoflake
[Pyflakes]: https://github.com/PyCQA/pyflakes
[Pylint]: https://pylint.readthedocs.io/en/latest/user_guide/messages/warning/unused-import.html
[Unimport]: https://github.com/hakancelikdev/unimport

## Installation

```bash
pip install import-analyzer-py
```

Or install from source:

```bash
git clone https://github.com/cmyui/import-analyzer-py
cd import-analyzer-py
pip install .
```

## pre-commit

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/cmyui/import-analyzer-py
    rev: v0.1.2  # or latest version
    hooks:
      # Cross-file analysis (recommended) - analyzes entire project
      - id: import-analyzer

      # Or for faster single-file analysis on changed files only:
      # - id: import-analyzer-single-file
```

The cross-file hook runs with all features enabled by default:
`--fix --warn-implicit-reexports --warn-circular --warn-unreachable`

To customize:

```yaml
hooks:
  - id: import-analyzer
    args: [.]  # check only, no warnings
  - id: import-analyzer
    args: [., --fix]  # fix but no warnings
```

## Usage

### Cross-file mode (default)

Cross-file mode follows imports from an entry point and tracks re-exports across your codebase. This prevents false positives when imports are used by other files.

```bash
# Analyze from entry point (follows imports)
import-analyzer main.py

# Analyze entire directory
import-analyzer src/

# Fix all unused imports (including cascaded ones)
import-analyzer --fix main.py

# Warn about implicit re-exports (imports used by other files but not in __all__)
import-analyzer --warn-implicit-reexports main.py

# Warn about circular imports
import-analyzer --warn-circular main.py

# Warn about files that become unreachable after fixing
import-analyzer --warn-unreachable main.py

# Quiet mode (summary only)
import-analyzer -q main.py
```

### Single-file mode

For simple use cases or when you want to analyze files independently:

```bash
# Check files independently (no cross-file tracking)
import-analyzer --single-file myfile.py

# Check multiple files
import-analyzer --single-file src/*.py
```

### Exit codes

| Code | Meaning                                       |
| ---- | --------------------------------------------- |
| 0    | No unused imports found (or `--fix` was used) |
| 1    | Unused imports found                          |

## Features

### Cross-file analysis

- **Re-export tracking**: Imports used by other files are preserved
- **Cascade detection**: Finds all unused imports in a single pass, even when removing one exposes another
- **Circular import detection**: Warns about import cycles
- **Implicit re-export warnings**: Identifies re-exports missing from `__all__`
- **Unreachable file detection**: Warns about files that become dead code after fixing imports

### Single-file analysis

- Detects unused `import X` and `from X import Y` statements
- Handles aliased imports (`import X as Y`, `from X import Y as Z`)
- Recognizes usage in:
  - Function calls and attribute access
  - Type annotations (including forward references / string annotations)
  - Decorators and base classes
  - Default argument values
  - `__all__` exports
- Skips `__future__` imports (they have side effects)
- Respects `# noqa: F401` comments (matches flake8 behavior)
- Full scope analysis with LEGB rule:
  - Correctly handles function parameters that shadow imports
  - Handles class scope quirks (class body doesn't enclose nested functions)
  - Supports comprehension scopes and walrus operator bindings
  - Respects `global` and `nonlocal` declarations

### Directory exclusions

The tool automatically skips common non-source directories:

- Virtual environments: `.venv`, `venv`, `.env`, `env`
- Build artifacts: `build`, `dist`, `*.egg-info`
- Cache directories: `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`
- Version control: `.git`, `.hg`, `.svn`
- Other: `node_modules`, `.tox`, `.nox`, `.eggs`

### Autofix

- Safely handles empty blocks by inserting `pass`
- Partial removal from multi-import statements
- Handles semicolon-separated statements
- Handles backslash line continuations

## Examples

### Single-file example

Before:

```python
import os
import sys  # unused
from typing import List, Optional  # List unused
from pathlib import Path

def get_home() -> Optional[Path]:
    return Path(os.environ.get("HOME"))
```

After (`--fix`):

```python
import os
from typing import Optional
from pathlib import Path

def get_home() -> Optional[Path]:
    return Path(os.environ.get("HOME"))
```

### Cross-file re-export example

```python
# utils.py
from typing import List  # NOT unused - re-exported to main.py

# main.py
from utils import List
x: List[int] = []
```

Running `import-analyzer main.py` correctly preserves the `List` import in `utils.py` because it's used by `main.py`.

### Cascade detection example

```python
# main.py
from helpers import List  # unused - not used locally

# helpers.py
from utils import List    # becomes unused when main.py's import is removed

# utils.py
from typing import List   # becomes unused when helpers.py's import is removed
```

Running `import-analyzer --fix main.py` removes all three imports in a single pass.

Note: Imports listed in `__all__` are always considered "used" (public API declaration) and won't be removed by cascade detection. This matches the behavior of flake8, ruff, and autoflake.

### noqa comments

The tool respects `# noqa` comments matching flake8 behavior:

```python
import os  # noqa: F401  - kept (F401 = unused import)
import sys  # noqa       - kept (bare noqa suppresses all)
import re  # noqa: E501  - flagged (wrong code)
```

For multi-line imports, noqa applies per-line:

```python
from typing import (
    List,  # noqa: F401  - kept
    Dict,  # flagged (no noqa)
)
```

## Known Limitations

- **Star imports**: `from X import *` cannot be analyzed statically
- **Dynamic imports**: `importlib.import_module()` calls are not tracked
- **Namespace packages**: PEP 420 namespace packages are not supported

## Development

### Setup

```bash
git clone https://github.com/cmyui/import-analyzer-py
cd import-analyzer-py
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Running tests

```bash
# Run with pytest
pytest tests/ -v

# Run with tox (multiple Python versions)
tox

# Run with coverage
tox -e py
```

### Project structure

```
.
├── import_analyzer/
│   ├── __init__.py          # Public API exports
│   ├── __main__.py          # Entry point for python -m
│   ├── _main.py             # CLI and orchestration
│   ├── _data.py             # Data classes (ImportInfo, ModuleInfo, etc.)
│   ├── _ast_helpers.py      # AST visitors for import/usage collection
│   ├── _detection.py        # Single-file detection logic
│   ├── _autofix.py          # Autofix logic
│   ├── _resolution.py       # Module resolution (resolves imports to files)
│   ├── _graph.py            # Import graph construction
│   ├── _cross_file.py       # Cross-file analysis with cascade detection
│   └── _format.py           # Output formatting
├── tests/
│   ├── detection_test.py
│   ├── aliased_imports_test.py
│   ├── shadowed_imports_test.py
│   ├── scope_analysis_test.py
│   ├── special_imports_test.py
│   ├── type_annotations_test.py
│   ├── autofix_test.py
│   ├── file_operations_test.py
│   ├── cli_test.py
│   ├── resolution_test.py   # Module resolution tests
│   ├── graph_test.py        # Import graph tests
│   ├── cross_file_test.py   # Cross-file analysis tests
│   └── format_test.py       # Output formatting tests
├── pyproject.toml
├── tox.ini
└── .github/workflows/ci.yml
```

## License

MIT
