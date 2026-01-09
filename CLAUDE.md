# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/detection_test.py -v

# Run a specific test by name
pytest tests/ -v -k "test_shadowed_by_assignment"

# Run tests with coverage
tox -e py

# Run tests across all Python versions (3.10-3.14)
tox

# Run pre-commit hooks
pre-commit run --all-files
```

## Architecture

This is a multi-module Python linter that detects and autofixes unused imports using AST analysis.

### Package Structure

```
remove_unused_imports/
  __init__.py          # Public API exports
  __main__.py          # Entry point for `python -m remove_unused_imports`
  _main.py             # CLI and orchestration (main, check_file, collect_python_files)
  _data.py             # Data classes (ImportInfo)
  _ast_helpers.py      # AST visitors (ImportExtractor, NameUsageCollector, etc.)
  _detection.py        # Detection logic (find_unused_imports)
  _autofix.py          # Autofix logic (remove_unused_imports)
```

### Core Components

**`_data.py`**: Contains `ImportInfo` dataclass for storing import metadata.

**`_ast_helpers.py`**: AST visitors and helpers:
- `ImportExtractor`: Collects all imports, tracking bound names, modules, line numbers. Skips `__future__` imports.
- `NameUsageCollector`: Finds all name usages. Only counts `ast.Load` contexts (not `Store`) for correct shadowing.
- `StringAnnotationVisitor`: Parses string literals as type annotations for forward references.
- `collect_dunder_all_names`: Extracts names from `__all__` so exports aren't flagged.

**`_detection.py`**: Contains `find_unused_imports()` which coordinates the visitors.

**`_autofix.py`**: Contains `remove_unused_imports()` which:
- Partial removal from multi-import statements (`from X import a, b, c` → `from X import a`)
- Inserts `pass` when removing imports would leave a block empty

**`_main.py`**: CLI entry point and file handling (`main`, `check_file`, `collect_python_files`).

### Test Organization

Tests follow pyupgrade patterns: one file per feature, heavy use of `pytest.param()` with descriptive IDs, `_noop` suffix for "should NOT flag" tests.
