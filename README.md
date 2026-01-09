# unused-import-linter

[![build status](https://github.com/cmyui/unused-import-detector/actions/workflows/ci.yml/badge.svg)](https://github.com/cmyui/unused-import-detector/actions/workflows/ci.yml)

A Python linter that detects and automatically removes unused imports.

## Installation

```bash
pip install unused-import-linter
```

Or install from source:

```bash
git clone https://github.com/cmyui/unused-import-detector
cd unused-import-detector
pip install .
```

## Usage

```bash
# Check a single file
unused-import-linter myfile.py

# Check a directory recursively
unused-import-linter src/

# Automatically fix unused imports
unused-import-linter --fix myfile.py

# Quiet mode (summary only)
unused-import-linter -q src/
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | No unused imports found (or `--fix` was used) |
| 1 | Unused imports found |

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
- Detects shadowed imports (assignment, loop variables, `with` targets, etc.)
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

- **No scope analysis**: Function parameters that shadow imports aren't detected as shadowing if used within the function body
- **Star imports ignored**: `from X import *` cannot be analyzed

## Development

### Setup

```bash
git clone https://github.com/cmyui/unused-import-detector
cd unused-import-detector
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
├── unused_import_linter.py     # Main module
├── tests/
│   ├── detection_test.py       # Basic detection tests
│   ├── aliased_imports_test.py # Aliased import tests
│   ├── shadowed_imports_test.py# Shadowed import tests
│   ├── special_imports_test.py # __future__, __all__, TYPE_CHECKING
│   ├── type_annotations_test.py# Type annotation tests
│   ├── autofix_test.py         # Autofix tests
│   └── file_operations_test.py # File/directory tests
├── pyproject.toml
├── tox.ini
└── .github/workflows/ci.yml
```

## License

MIT
