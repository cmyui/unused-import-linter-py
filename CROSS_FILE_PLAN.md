# Plan: Cross-File Import Tracking

## Goal

Transform the tool from single-file analysis to cross-file import tracking. When run against an entry point, the tool will:

1. Follow imports like Python's runtime (entry point → reachable files only)
2. Track external (stdlib/third-party) usage across the project
3. Warn when imports are implicitly re-exported (used by other files but not in `__all__`)

**Example:**
```python
# utils.py
from typing import List  # NOT unused - re-exported to main.py

# main.py
from utils import List  # Uses List from utils
x: List[int] = []
```

---

## CLI Interface

```bash
# Entry point mode: follow imports from a single file
remove-unused-imports main.py
remove-unused-imports main.py --fix

# Whole project mode: analyze all files in directory
remove-unused-imports src/
remove-unused-imports src/ --fix

# Options
remove-unused-imports main.py --warn-implicit-reexports
remove-unused-imports main.py --warn-circular
remove-unused-imports src/ --quiet
```

**Optional warnings:**
- `--warn-implicit-reexports`: Flag imports used by other files but not in `__all__`
- `--warn-circular`: Report circular import chains (e.g., `a.py → b.py → c.py → a.py`)

**Two modes (auto-detected):**
1. **Entry point mode** (file argument): Start from that file, follow imports recursively
2. **Whole project mode** (directory argument): Build complete import graph of all `.py` files

**Path resolution:** Works exactly like `python main.py`:
- Entry point's parent directory is the source root (like `sys.path[0]`)
- Respects `PYTHONPATH` environment variable if set

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Entry Point                              │
│                    --entry-point main.py                         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Module Resolver                              │
│  - Resolves import statements to file paths                      │
│  - Handles relative imports (from . import x)                    │
│  - Detects external modules (stdlib/third-party)                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Graph Builder                               │
│  - BFS from entry point, following imports                       │
│  - Builds ImportGraph with nodes (files) and edges (imports)     │
│  - Detects circular dependencies                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Cross-File Analyzer                            │
│  - Runs single-file analysis on each module                      │
│  - Propagates usage through re-exports                           │
│  - Detects implicit re-exports (missing from __all__)            │
│  - Aggregates external module usage                              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Results / Autofix                           │
│  - Report unused imports per file                                │
│  - Warn on implicit re-exports                                   │
│  - Safe autofix (respects re-export dependencies)                │
└─────────────────────────────────────────────────────────────────┘
```

---

## New Data Structures

### `_data.py` additions

```python
@dataclass
class ModuleInfo:
    """Information about a Python module in the project."""
    file_path: Path
    module_name: str          # "mypackage.submodule.utils"
    is_package: bool          # True for __init__.py
    imports: list[ImportInfo]
    exports: set[str]         # Names in __all__
    defined_names: set[str]   # Classes, functions, variables defined

@dataclass
class ImportEdge:
    """An edge in the import graph."""
    importer: Path
    imported: Path | None     # None = external module
    names: set[str]           # Names being imported
    is_external: bool

@dataclass
class ImplicitReexport:
    """Import used by other files but not in __all__."""
    source_file: Path
    import_name: str
    used_by: set[Path]
```

---

## New Modules

### `_resolution.py` - Module Resolution

```python
class ModuleResolver:
    def __init__(self, entry_point: Path):
        self.source_root = entry_point.parent  # Like sys.path[0]
        self.pythonpath = self._parse_pythonpath()  # From env var
        self.external_modules = self._get_external_modules()

    def resolve_import(self, module: str, from_file: Path, level: int) -> Path | None
    def is_external(self, module: str) -> bool
    def get_module_name(self, file_path: Path) -> str
```

**Resolution Algorithm (mirrors Python):**
1. Relative imports: Calculate package path from importing file, apply level (dots)
2. Absolute imports: Search source_root first, then PYTHONPATH entries
3. Check if external (stdlib/installed) before searching
4. Packages: Resolve to `__init__.py`

### `_graph.py` - Import Graph

```python
class ImportGraph:
    nodes: dict[Path, ModuleInfo]
    edges: list[ImportEdge]

    def get_imports(self, file: Path) -> list[ImportEdge]
    def get_importers(self, file: Path) -> list[ImportEdge]
    def find_cycles(self) -> list[list[Path]]
    def topological_order(self) -> list[Path]

class GraphBuilder:
    def build(self, entry_point: Path) -> ImportGraph
    # BFS from entry point, following resolved imports
```

### `_cross_file.py` - Cross-File Analysis

```python
@dataclass
class CrossFileResult:
    unused_imports: dict[Path, list[ImportInfo]]
    implicit_reexports: list[ImplicitReexport]
    external_usage: dict[str, set[Path]]  # module -> files using it
    circular_imports: list[list[Path]]

class CrossFileAnalyzer:
    def analyze(self, graph: ImportGraph) -> CrossFileResult
    # 1. Single-file analysis per module
    # 2. Propagate usage through re-exports
    # 3. Find implicit re-exports
    # 4. Aggregate external usage

class CrossFileAutofix:
    def compute_safe_removals(self) -> dict[Path, list[ImportInfo]]
    # Only remove if: unused locally AND not re-exported AND not used by other files
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `_data.py` | Modify | Add `ModuleInfo`, `ImportEdge`, `ImplicitReexport` |
| `_resolution.py` | Create | Module resolver (mirrors Python's path resolution) |
| `_graph.py` | Create | Import graph, graph builder |
| `_cross_file.py` | Create | Cross-file analyzer, safe autofix |
| `_ast_helpers.py` | Modify | Add `level` to ImportExtractor, add `DefinitionCollector` |
| `_main.py` | Modify | Replace single-file logic with cross-file analysis |

---

## Implementation Phases

### Phase 1: Module Resolution
- Implement `ModuleResolver` (mirrors Python's import system)
- Use entry point's parent as source root (like `sys.path[0]`)
- Parse `PYTHONPATH` environment variable
- Handle relative imports (`from . import x`, `from ..parent import y`)
- Detect external modules using `sys.stdlib_module_names` + `importlib.metadata`
- **Test:** Resolution of various import patterns

### Phase 2: Import Graph
- Implement `ImportGraph` and `GraphBuilder`
- BFS traversal from entry point
- Cycle detection (Tarjan's algorithm)
- **Test:** Graph construction, cycle detection

### Phase 3: Cross-File Analysis
- Implement `CrossFileAnalyzer`
- Run existing single-file analysis per module
- Propagate re-export usage
- Detect implicit re-exports
- **Test:** Multi-file unused detection, re-export scenarios

### Phase 4: CLI Integration
- Update `main()` to use cross-file analysis by default
- Auto-detect entry point mode (file) vs whole project mode (directory)
- Output formatting for cross-file results
- **Test:** End-to-end CLI tests

### Phase 5: Cross-File Autofix
- Implement `CrossFileAutofix`
- Safe removal logic (respect re-exports)
- Process in dependency order
- **Test:** Autofix preserves re-exports

---

## Edge Cases

1. **Circular imports:** Detect and report, process as SCCs
2. **Star imports:** Use `__all__` if available, otherwise skip
3. **Dynamic imports:** Cannot analyze, document limitation
4. **TYPE_CHECKING blocks:** Treat as annotation-only imports
5. **`__init__.py` re-exports:** Track what packages expose

---

## Verification

1. **Existing tests pass:** `pytest tests/ -v`
2. **New tests pass:** Cross-file scenarios in `tests/cross_file_test.py`
3. **Manual test with multi-file project:**
   ```
   test_project/
     main.py          # Entry point
     utils.py         # Imports typing.List, re-exports to main
     helpers.py       # Unused, not reachable from main
   ```
   - `utils.py`'s `List` import should NOT be flagged
   - `helpers.py` should not be analyzed (unreachable)
   - `--warn-implicit-reexports` should warn about `List` in utils.py

---

## Out of Scope (Future Work)

- Dynamic import analysis (`importlib.import_module`)
- Namespace packages (PEP 420)
- Editable installs / symlinks
- Parallel graph construction
