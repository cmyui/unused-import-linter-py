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

This is a multi-module Python linter that detects and autofixes unused imports using AST analysis. It supports both single-file and cross-file analysis modes.

### Package Structure

```
import_analyzer/
  __init__.py          # Public API exports
  __main__.py          # Entry point for `python -m import_analyzer`
  _main.py             # CLI and orchestration (main, check_file, check_cross_file)
  _data.py             # Data classes (ImportInfo, ModuleInfo, ImportEdge, etc.)
  _ast_helpers.py      # AST visitors (ImportExtractor, NameUsageCollector, etc.)
  _detection.py        # Single-file detection logic (find_unused_imports)
  _autofix.py          # Autofix logic (import_analyzer)
  _resolution.py       # Module resolution (resolves import statements to file paths)
  _graph.py            # Import graph construction (builds dependency graph from entry point)
  _cross_file.py       # Cross-file analysis with cascade detection
  _format.py           # Output formatting for CLI
```

### Core Components

**`_data.py`**: Data classes:
- `ImportInfo`: Import metadata (name, module, line numbers, etc.)
- `ModuleInfo`: Module metadata (file path, imports, exports, defined names)
- `ImportEdge`: Edge in import graph (importer → imported, names)
- `ImplicitReexport`: Re-exported import not in `__all__`

**`_ast_helpers.py`**: AST visitors and helpers:
- `ImportExtractor`: Collects all imports with `level` for relative imports. Skips `__future__`.
- `ScopeAwareNameCollector`: Full scope analysis with LEGB rule:
  - `ScopeType` enum: MODULE, FUNCTION, CLASS, COMPREHENSION
  - `Scope` dataclass: tracks bindings and scope type
  - `ScopeStack`: manages scope chain with `resolves_to_module_scope()` for LEGB lookup
  - Handles all binding forms: assignments, function params, for/with targets, except handlers, match patterns, walrus operator
  - Respects `global`/`nonlocal` declarations
  - Handles class scope quirk (doesn't enclose nested functions)
- `DefinitionCollector`: Collects all defined names (classes, functions, variables) in a module
- `StringAnnotationVisitor`: Parses string literals as type annotations for forward references.
- `collect_dunder_all_names`: Extracts names from `__all__` so exports aren't flagged.

**`_detection.py`**: Contains `find_unused_imports()` for single-file analysis.
- Respects `# noqa: F401` comments (matches flake8 behavior)
- noqa keyword is case-insensitive, but codes are case-sensitive
- Handles noqa on multi-line imports (per-alias line) and backslash continuations

**`_autofix.py`**: Contains `remove_unused_imports()` which:
- Partial removal from multi-import statements
- Inserts `pass` when removing imports would leave a block empty
- Handles semicolon-separated statements with surgical removal
- Handles backslash line continuations

**`_resolution.py`**: Module resolution:
- `ModuleResolver`: Resolves import statements to file paths
- Handles relative imports (`from . import x`, `from ..parent import y`)
- Detects external modules (stdlib + installed packages)
- Respects PYTHONPATH

**`_graph.py`**: Import graph:
- `ImportGraph`: Nodes (files) and edges (imports)
- `build_import_graph()`: BFS from entry point, following imports
- `build_import_graph_from_directory()`: Analyzes all files in directory
- `find_cycles()`: Detects circular import chains (Tarjan's algorithm for SCCs)
- **Submodule traversal**: Handles `from pkg import submod` where submod isn't in `pkg/__init__.py`
- **Directory exclusions**: Skips `.venv`, `node_modules`, `__pycache__`, `.git`, `build`, `dist`, etc.

**`_cross_file.py`**: Cross-file analysis:
- `CrossFileAnalyzer`: Main analyzer class
- `CrossFileResult`: Results (unused_imports, implicit_reexports, circular_imports, unreachable_files)
- **`__all__` as usage**: Imports listed in `__all__` are always considered "used" (public API). This matches flake8/ruff/autoflake behavior. No cascade detection through `__all__`.
- **Cascade detection**: Iterates until stable to find all unused imports in one pass
  - When import A is unused, check if B's import (re-exported to A) is now unused
  - Tracks file reachability: imports from unreachable files don't count as consumers
  - Continues until no new unused imports are found
  - Exception: `__init__.py` files without `__all__` have implicit re-exports that can cascade
- **Unreachable file detection**: Two concepts tracked separately:
  - "Potentially unreachable" (no direct edges): Used internally for cascade
  - "Truly unreachable" (no edges AND no reachable ancestors): Reported to user
  - Handles parent package imports: `import pkg` + `pkg.submod.x` keeps submodules accessible

**`_format.py`**: Output formatting:
- Groups unused imports by file, then by line
- Shows relative paths from entry point
- Sections for unused imports, implicit re-exports, circular imports, unreachable files
- Summary with counts

**`_main.py`**: CLI entry point:
- `main()`: Argument parsing, mode selection
- `check_file()`: Single-file mode
- `check_cross_file()`: Cross-file mode (default)

### Test Organization

Tests follow pyupgrade patterns: one file per feature, heavy use of `pytest.param()` with descriptive IDs, `_noop` suffix for "should NOT flag" tests. Flat function style (no test classes).
