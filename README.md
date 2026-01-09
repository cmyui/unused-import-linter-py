# remove-unused-imports

[![build status](https://github.com/cmyui/remove-unused-imports-py/actions/workflows/ci.yml/badge.svg)](https://github.com/cmyui/remove-unused-imports-py/actions/workflows/ci.yml)

A Python linter that detects and automatically removes unused imports.

## Installation

```bash
pip install remove-unused-imports
```

Or install from source:

```bash
git clone https://github.com/cmyui/remove-unused-imports-py
cd remove-unused-imports-py
pip install .
```

## Usage

```bash
# Check a single file
remove-unused-imports myfile.py

# Check a directory recursively
remove-unused-imports src/

# Automatically fix unused imports
remove-unused-imports --fix myfile.py

# Quiet mode (summary only)
remove-unused-imports -q src/
```

### Exit codes

| Code | Meaning                                       |
| ---- | --------------------------------------------- |
| 0    | No unused imports found (or `--fix` was used) |
| 1    | Unused imports found                          |

## Features

- Detects unused `import X` and `from X import Y` statements
- Handles aliased imports (`import X as Y`, `from X import Y as Z`)
- Recognizes usage in:
  - Function calls and attribute access
  - Type annotations (including forward references / string annotations)
  - Decorators and base classes
  - Default argument values
  - `__all__` exports
- Skips `__future__` imports (they have side effects)
- Detects shadowed imports (assignment, function parameters, loop variables, `with` targets, etc.)
- Full scope analysis (correctly handles function parameters that shadow imports)
- Autofix safely handles empty blocks by inserting `pass`

## Examples

### Before

```python
import os
import sys  # unused
from typing import List, Optional  # List unused
from pathlib import Path

def get_home() -> Optional[Path]:
    return Path(os.environ.get("HOME"))
```

### After (`--fix`)

```python
import os
from typing import Optional
from pathlib import Path

def get_home() -> Optional[Path]:
    return Path(os.environ.get("HOME"))
```

## Known Limitations

- **Star imports ignored**: `from X import *` cannot be analyzed

## Development

### Setup

```bash
git clone https://github.com/cmyui/remove-unused-imports-py
cd remove-unused-imports-py
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
├── remove_unused_imports/
│   ├── __init__.py          # Public API exports
│   ├── __main__.py          # Entry point for python -m
│   ├── _main.py             # CLI and orchestration
│   ├── _data.py             # Data classes
│   ├── _ast_helpers.py      # AST visitors
│   ├── _detection.py        # Detection logic
│   └── _autofix.py          # Autofix logic
├── tests/
│   ├── detection_test.py
│   ├── aliased_imports_test.py
│   ├── shadowed_imports_test.py
│   ├── special_imports_test.py
│   ├── type_annotations_test.py
│   ├── autofix_test.py
│   └── file_operations_test.py
├── pyproject.toml
├── tox.ini
└── .github/workflows/ci.yml
```

## License

MIT
