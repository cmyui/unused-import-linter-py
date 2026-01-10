"""Tests for cross-file import analysis (_cross_file.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from import_analyzer._cross_file import analyze_cross_file
from import_analyzer._graph import build_import_graph
from import_analyzer._graph import build_import_graph_from_directory
from import_analyzer._main import check_cross_file

# =============================================================================
# Re-export detection tests
# =============================================================================


@pytest.fixture
def project_with_reexport():
    """Create a project where an import is re-exported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports List from utils (re-exported)
        (root / "main.py").write_text(
            "from utils import List\n" "x: List[int] = []\n",
        )

        # utils.py imports List from typing and re-exports it
        (root / "utils.py").write_text(
            "from typing import List, Dict  # Dict is unused\n",
        )

        yield root


def test_reexported_import_not_unused(project_with_reexport):
    """Re-exported imports should NOT be marked as unused."""
    graph = build_import_graph(project_with_reexport / "main.py")
    result = analyze_cross_file(graph)

    # utils.py has List and Dict imports
    # List is re-exported to main.py, so only Dict should be unused
    utils_unused = result.unused_imports.get(project_with_reexport / "utils.py", [])
    unused_names = {imp.name for imp in utils_unused}

    assert "Dict" in unused_names
    assert "List" not in unused_names


def test_implicit_reexport_detected(project_with_reexport):
    """Should detect imports re-exported without __all__."""
    graph = build_import_graph(project_with_reexport / "main.py")
    result = analyze_cross_file(graph)

    # List is re-exported but not in __all__
    assert len(result.implicit_reexports) == 1
    reexport = result.implicit_reexports[0]
    assert reexport.source_file == project_with_reexport / "utils.py"
    assert reexport.import_name == "List"
    assert project_with_reexport / "main.py" in reexport.used_by


def test_external_usage_aggregated(project_with_reexport):
    """Should track which files use which external modules."""
    graph = build_import_graph(project_with_reexport / "main.py")
    result = analyze_cross_file(graph)

    assert "typing" in result.external_usage
    assert project_with_reexport / "utils.py" in result.external_usage["typing"]


# =============================================================================
# Explicit re-export tests
# =============================================================================


def test_explicit_reexport_not_flagged():
    """Explicit re-exports (in __all__) should not be flagged as implicit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "main.py").write_text(
            "from utils import List\n" "x: List[int] = []\n",
        )

        (root / "utils.py").write_text(
            "from typing import List\n" "__all__ = ['List']\n",
        )

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # List is explicitly exported, so should not be implicit reexport
        implicit_names = {r.import_name for r in result.implicit_reexports}
        assert "List" not in implicit_names


# =============================================================================
# No re-export tests
# =============================================================================


def test_unused_import_when_no_reexport():
    """Unused imports should be detected when not re-exported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "main.py").write_text(
            "from typing import List  # unused\n" "x = 1\n",
        )

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        main_unused = result.unused_imports.get(root / "main.py", [])
        assert len(main_unused) == 1
        assert main_unused[0].name == "List"


# =============================================================================
# Circular import tests
# =============================================================================


def test_circular_import_detected():
    """Should detect circular imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "a.py").write_text("from b import x\n")
        (root / "b.py").write_text("from c import y\n")
        (root / "c.py").write_text("from a import z\n")

        graph = build_import_graph(root / "a.py")
        result = analyze_cross_file(graph)

        assert len(result.circular_imports) == 1
        cycle_names = {p.name for p in result.circular_imports[0]}
        assert cycle_names == {"a.py", "b.py", "c.py"}


def test_no_circular_when_none():
    """Should report no circular imports when there are none."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "main.py").write_text("import utils\n")
        (root / "utils.py").write_text("# no imports\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        assert result.circular_imports == []


# =============================================================================
# Defined names vs re-exports tests
# =============================================================================


def test_defined_name_not_reexport():
    """Names defined in file should not be re-exports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "main.py").write_text("from utils import helper\n" "helper()\n")

        (root / "utils.py").write_text(
            "from typing import List  # unused\n" "def helper() -> None: pass\n",
        )

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # helper is defined in utils.py, not an import
        # So it's not a re-export, just a normal export
        # List is unused
        utils_unused = result.unused_imports.get(root / "utils.py", [])
        assert len(utils_unused) == 1
        assert utils_unused[0].name == "List"

        # helper should not be in implicit re-exports
        implicit_names = {r.import_name for r in result.implicit_reexports}
        assert "helper" not in implicit_names


# =============================================================================
# Multiple/chained re-export tests
# =============================================================================


def test_chain_of_reexports():
    """Should handle chain of re-exports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main imports List from b
        (root / "main.py").write_text("from b import List\n" "x: List[int] = []\n")

        # b imports List from a
        (root / "b.py").write_text("from a import List\n")

        # a imports List from typing
        (root / "a.py").write_text("from typing import List\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # Neither a.py nor b.py should have List as unused
        # because it's re-exported through the chain
        for path, unused in result.unused_imports.items():
            unused_names = {imp.name for imp in unused}
            assert (
                "List" not in unused_names
            ), f"List should not be unused in {path}"


# =============================================================================
# Partial re-export tests
# =============================================================================


def test_partial_reexport():
    """Should correctly identify partially re-exported imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "main.py").write_text(
            "from utils import List  # only List is used\n" "x: List[int] = []\n",
        )

        (root / "utils.py").write_text(
            "from typing import List, Dict, Optional  # Dict and Optional unused\n",
        )

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        utils_unused = result.unused_imports.get(root / "utils.py", [])
        unused_names = {imp.name for imp in utils_unused}

        assert "List" not in unused_names  # re-exported
        assert "Dict" in unused_names  # not re-exported
        assert "Optional" in unused_names  # not re-exported


# =============================================================================
# Cascade detection tests
# =============================================================================


def test_cascade_unused_when_consumer_removed():
    """Should cascade unused detection when consumer import is removed.

    When A imports X from B (but doesn't use X), and B imports X from C
    (only for re-export to A), removing A's import should also mark B's
    import as unused in a single analysis pass.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports List from helpers but doesn't use it
        (root / "main.py").write_text(
            "from helpers import List  # unused!\n" "x = 1\n",
        )

        # helpers.py imports List from utils (only for re-export to main)
        (root / "helpers.py").write_text("from utils import List\n")

        # utils.py imports List from typing (only for re-export to helpers)
        (root / "utils.py").write_text("from typing import List\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # All three imports should be unused in a single pass:
        # 1. main.py's List is unused locally
        # 2. helpers.py's List is only re-exported to main, which is being removed
        # 3. utils.py's List is only re-exported to helpers, which is being removed

        main_unused = result.unused_imports.get(root / "main.py", [])
        helpers_unused = result.unused_imports.get(root / "helpers.py", [])
        utils_unused = result.unused_imports.get(root / "utils.py", [])

        assert any(imp.name == "List" for imp in main_unused), "List should be unused in main.py"
        assert any(imp.name == "List" for imp in helpers_unused), "List should be unused in helpers.py"
        assert any(imp.name == "List" for imp in utils_unused), "List should be unused in utils.py"


def test_cascade_partial_chain():
    """Cascade should stop when an import is actually used."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports List from helpers but doesn't use it
        (root / "main.py").write_text(
            "from helpers import List  # unused!\n" "x = 1\n",
        )

        # helpers.py imports List and uses it locally too
        (root / "helpers.py").write_text(
            "from utils import List\n" "data: List[int] = []\n",
        )

        # utils.py imports List from typing
        (root / "utils.py").write_text("from typing import List\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # main.py's List is unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "List" for imp in main_unused)

        # helpers.py's List is used locally, so NOT unused
        helpers_unused = result.unused_imports.get(root / "helpers.py", [])
        assert not any(imp.name == "List" for imp in helpers_unused)

        # utils.py's List is re-exported to helpers (which uses it), so NOT unused
        utils_unused = result.unused_imports.get(root / "utils.py", [])
        assert not any(imp.name == "List" for imp in utils_unused)


def test_cascade_multiple_consumers():
    """Import should remain if ANY consumer still uses it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py doesn't use List
        (root / "main.py").write_text(
            "from utils import List  # unused\n"
            "from other import helper\n"
            "helper()\n",
        )

        # other.py uses List from utils
        (root / "other.py").write_text(
            "from utils import List\n"
            "def helper() -> List[int]: return []\n",
        )

        # utils.py imports List from typing
        (root / "utils.py").write_text("from typing import List\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # main.py's List is unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "List" for imp in main_unused)

        # other.py's List is used locally
        other_unused = result.unused_imports.get(root / "other.py", [])
        assert not any(imp.name == "List" for imp in other_unused)

        # utils.py's List is still re-exported to other.py, so NOT unused
        utils_unused = result.unused_imports.get(root / "utils.py", [])
        assert not any(imp.name == "List" for imp in utils_unused)


def test_dunder_all_protects_imports_from_cascade():
    """Imports in __all__ should NOT be flagged as unused.

    Being listed in __all__ is an explicit declaration of public API.
    This matches the behavior of flake8, ruff, and autoflake.
    External consumers (outside the analyzed tree) may use these exports.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports Foo from pkg but doesn't use it
        (root / "main.py").write_text(
            "from pkg import Foo  # unused!\n" "x = 1\n",
        )

        # pkg/__init__.py imports Foo and exports it via __all__
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from pkg.foo import Foo\n" "__all__ = ['Foo']\n",
        )

        # pkg/foo.py defines Foo
        (pkg / "foo.py").write_text("class Foo: pass\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # main.py's Foo import is unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "Foo" for imp in main_unused), "Foo should be unused in main.py"

        # pkg/__init__.py's Foo import is in __all__, so it's considered "used" (public API)
        # and should NOT be flagged as unused
        init_unused = result.unused_imports.get(pkg / "__init__.py", [])
        assert not any(imp.name == "Foo" for imp in init_unused), (
            "Foo should NOT be unused in pkg/__init__.py (protected by __all__)"
        )


def test_dunder_all_protects_used_imports():
    """__all__ exports that are used should obviously not be flagged as unused."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports and uses Foo from pkg
        (root / "main.py").write_text(
            "from pkg import Foo\n" "f = Foo()\n",
        )

        # pkg/__init__.py imports Foo and exports it via __all__
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from pkg.foo import Foo\n" "__all__ = ['Foo']\n",
        )

        # pkg/foo.py defines Foo
        (pkg / "foo.py").write_text("class Foo: pass\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph)

        # main.py's Foo import is used
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert not any(imp.name == "Foo" for imp in main_unused)

        # pkg/__init__.py's Foo import is in __all__ (and also used by main.py)
        init_unused = result.unused_imports.get(pkg / "__init__.py", [])
        assert not any(imp.name == "Foo" for imp in init_unused)


# =============================================================================
# File reachability cascade tests
# =============================================================================


def test_cascade_file_unreachable():
    """Should cascade unused when removing import makes file unreachable.

    When a module import is removed (because all imported names are unused),
    the target file becomes unreachable. Imports from that unreachable file
    should no longer count as "consumers" of re-exports.

    Scenario:
    - main.py: `from consumer import run` (unused)
    - consumer.py: `from utils import Foo; def run() -> Foo: pass`
    - utils.py: `from typing import List as Foo` (re-export only)

    When main.py's import is removed:
    - consumer.py becomes unreachable
    - Its import from 'utils' no longer counts as a consumer
    - utils.py's Foo import should become unused
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports run from consumer but doesn't use it
        (root / "main.py").write_text(
            "from consumer import run  # unused!\n" "x = 1\n",
        )

        # consumer.py imports Foo from utils and uses it locally
        (root / "consumer.py").write_text(
            "from utils import Foo\n" "def run() -> Foo: pass\n",
        )

        # utils.py imports Foo from typing and re-exports it (but doesn't use locally)
        (root / "utils.py").write_text("from typing import List as Foo\n")

        graph = build_import_graph(root / "main.py")
        # Pass entry point for file reachability tracking
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # main.py's run import is unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "run" for imp in main_unused)

        # utils.py's Foo import should be unused
        # because consumer.py (the only consumer) becomes unreachable
        utils_unused = result.unused_imports.get(root / "utils.py", [])
        assert any(imp.name == "Foo" for imp in utils_unused), (
            "Foo should be unused in utils.py "
            "(consumer file becomes unreachable)"
        )


def test_cascade_file_still_reachable_via_other_path():
    """Should NOT cascade if file is still reachable via another import."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports from both pkg.a (unused) and pkg.b (used)
        (root / "main.py").write_text(
            "from pkg import module_a  # unused!\n"
            "from pkg import module_b\n"
            "module_b.run()\n",
        )

        # pkg/__init__.py re-exports both modules
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from pkg import module_a\n" "from pkg import module_b\n",
        )

        # pkg/module_a.py imports Foo from types_pkg (unused when module_a is removed)
        (pkg / "module_a.py").write_text(
            "from types_pkg import Foo\n" "def helper() -> Foo: pass\n",
        )

        # pkg/module_b.py also imports Foo from types_pkg (and uses it)
        (pkg / "module_b.py").write_text(
            "from types_pkg import Foo\n"
            "def run() -> Foo: return Foo()\n",
        )

        # types_pkg/__init__.py re-exports Foo
        types_pkg = root / "types_pkg"
        types_pkg.mkdir()
        (types_pkg / "__init__.py").write_text("from types_pkg.foo import Foo\n")

        # types_pkg/foo.py defines Foo
        (types_pkg / "foo.py").write_text("class Foo: pass\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # main.py's module_a import is unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "module_a" for imp in main_unused)
        assert not any(imp.name == "module_b" for imp in main_unused)

        # types_pkg/__init__.py's Foo import should NOT be unused
        # because module_b still imports it (and module_b is still reachable)
        types_pkg_unused = result.unused_imports.get(types_pkg / "__init__.py", [])
        assert not any(imp.name == "Foo" for imp in types_pkg_unused)


def test_submodule_not_in_init_is_traversed():
    """Submodules not explicitly imported in __init__.py should still be traversed.

    This handles cases like `from mypkg import submodule` where
    `submodule` is a subpackage that's NOT imported in `mypkg/__init__.py`.
    Python allows this at runtime via auto-importing.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports a submodule not exported by parent __init__.py
        (root / "main.py").write_text(
            "from pkg import submodule\n" "submodule.do_thing()\n",
        )

        # pkg/__init__.py does NOT import submodule
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "# This package doesn't explicitly import submodule\n" "VERSION = '1.0'\n",
        )

        # pkg/submodule/__init__.py exists and has imports
        submodule = pkg / "submodule"
        submodule.mkdir()
        (submodule / "__init__.py").write_text(
            "from pkg.submodule.helper import do_thing\n",
        )

        # pkg/submodule/helper.py defines do_thing
        (submodule / "helper.py").write_text("def do_thing(): pass\n")

        graph = build_import_graph(root / "main.py")

        # Verify submodule/__init__.py is in the graph
        assert (submodule / "__init__.py") in graph.nodes, (
            "Submodule should be traversed even when not in parent __init__.py"
        )

        # Verify helper.py is also in the graph (transitive)
        assert (submodule / "helper.py") in graph.nodes, (
            "Files imported by submodule should also be traversed"
        )

        # Run analysis to ensure it works end-to-end
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # main.py's import should NOT be unused (it uses submodule.do_thing)
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert not any(imp.name == "submodule" for imp in main_unused)


def test_submodule_not_unreachable_when_parent_reachable():
    """Submodules should NOT be reported as unreachable if parent package is reachable.

    This handles patterns where:
    - `import pkg` makes the package reachable
    - `from pkg import submodule` is unused (code uses pkg.submodule instead)
    - But submodule is still accessible at runtime via pkg.submodule
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports the parent package AND the submodule (submodule import unused)
        (root / "main.py").write_text(
            "import pkg\n"
            "from pkg import submodule  # unused! uses pkg.submodule instead\n"
            "pkg.submodule.do_thing()\n",
        )

        # pkg/__init__.py
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("VERSION = '1.0'\n")

        # pkg/submodule/__init__.py
        submodule = pkg / "submodule"
        submodule.mkdir()
        (submodule / "__init__.py").write_text("def do_thing(): pass\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # The `from pkg import submodule` should be flagged as unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "submodule" for imp in main_unused)

        # But submodule should NOT be reported as unreachable
        # because pkg/__init__.py is still reachable (via `import pkg`)
        # and Python allows pkg.submodule access at runtime
        assert (submodule / "__init__.py") not in result.unreachable_files


def test_truly_unreachable_file_is_reported():
    """Files that become truly unreachable should be reported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports helper (unused)
        (root / "main.py").write_text(
            "from helper import unused_func  # unused!\n" "print('hello')\n",
        )

        # helper.py is a standalone module (not in a package)
        (root / "helper.py").write_text("def unused_func(): pass\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # The import should be flagged as unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "unused_func" for imp in main_unused)

        # helper.py should be reported as unreachable
        # because it's a standalone module with no parent package
        assert (root / "helper.py") in result.unreachable_files


def test_cascade_works_for_potentially_unreachable_but_not_reported():
    """Cascade should work for files that are potentially unreachable but have reachable ancestors.

    This tests the key differentiation:
    1. "Potentially unreachable" (no direct import edges) - used for cascade
    2. "Truly unreachable" (no edges AND no reachable ancestors) - reported to user

    A submodule that becomes potentially unreachable should:
    - Have its imports NOT count as consumers (cascade works)
    - NOT be reported as truly unreachable (has reachable ancestor)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports the parent package, and also imports submodule (unused)
        (root / "main.py").write_text(
            "import pkg\n"
            "from pkg import consumer  # unused! (never uses consumer directly)\n"
            "print(pkg.VERSION)\n",
        )

        # pkg/__init__.py defines VERSION
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("VERSION = '1.0'\n")

        # pkg/consumer.py imports Helper from pkg.helpers (re-export)
        (pkg / "consumer.py").write_text(
            "from pkg.helpers import Helper\n"
            "def use_helper() -> Helper: return Helper()\n",
        )

        # pkg/helpers.py defines Helper
        (pkg / "helpers.py").write_text("class Helper: pass\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # 1. main.py's consumer import should be flagged as unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "consumer" for imp in main_unused), (
            "consumer import should be unused in main.py"
        )

        # 2. pkg/consumer.py becomes "potentially unreachable" (no direct edges after removal)
        #    This means its import of Helper should NOT count as a consumer
        #    So pkg/helpers.py's Helper should... wait, Helper is defined, not imported
        #    Let me restructure this test...

        # Actually, let's verify the cascade by checking that consumer.py is NOT
        # in unreachable_files (has reachable ancestor pkg/__init__.py)
        assert (pkg / "consumer.py") not in result.unreachable_files, (
            "consumer.py should NOT be reported as truly unreachable "
            "(pkg/__init__.py is still reachable)"
        )


def test_cascade_detects_more_unused_via_potentially_unreachable():
    """Verify cascade finds additional unused imports through potentially unreachable files.

    This is the key test: when a file becomes potentially unreachable (for cascade),
    imports it was consuming should become unused, even though the file itself
    is not reported as truly unreachable.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # main.py imports parent pkg, and consumer submodule (unused)
        (root / "main.py").write_text(
            "import pkg\n"
            "from pkg import consumer  # unused!\n"
            "print(pkg.VERSION)\n",
        )

        # pkg/__init__.py re-exports SharedUtil from pkg.shared
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "VERSION = '1.0'\n" "from pkg.shared import SharedUtil\n",
        )

        # pkg/consumer.py is the ONLY user of SharedUtil from pkg
        (pkg / "consumer.py").write_text(
            "from pkg import SharedUtil\n"
            "def do_work() -> SharedUtil: return SharedUtil()\n",
        )

        # pkg/shared.py defines SharedUtil
        (pkg / "shared.py").write_text("class SharedUtil: pass\n")

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # 1. main.py's consumer import is unused
        main_unused = result.unused_imports.get(root / "main.py", [])
        assert any(imp.name == "consumer" for imp in main_unused)

        # 2. consumer.py is NOT reported as truly unreachable (has reachable ancestor)
        assert (pkg / "consumer.py") not in result.unreachable_files

        # 3. KEY TEST: Because consumer.py becomes "potentially unreachable",
        #    its import of SharedUtil no longer counts as a consumer.
        #    Therefore, pkg/__init__.py's SharedUtil re-export becomes unused!
        init_unused = result.unused_imports.get(pkg / "__init__.py", [])
        assert any(imp.name == "SharedUtil" for imp in init_unused), (
            "SharedUtil should be unused in pkg/__init__.py because consumer.py "
            "(the only consumer) is potentially unreachable. "
            f"Got unused: {[imp.name for imp in init_unused]}"
        )


# =============================================================================
# Package directory mode: source root and scope filtering tests
# =============================================================================


def test_package_directory_internal_imports_resolve():
    """When analyzing a package directory, internal imports should resolve.

    Bug fix: Previously, analyzing pkg/ set source_root=pkg/, causing
    `from pkg import X` in pkg/module.py to fail resolution (looked for
    pkg/pkg/__init__.py instead of pkg/__init__.py).

    Now source_root=pkg_parent/ so internal imports resolve correctly.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # Create a package with internal imports
        pkg = root / "mypkg"
        pkg.mkdir()

        # mypkg/__init__.py exports helper
        (pkg / "__init__.py").write_text(
            "from mypkg.utils import helper\n",
        )

        # mypkg/utils.py defines helper
        (pkg / "utils.py").write_text(
            "def helper(): pass\n",
        )

        # mypkg/module.py imports helper from the package
        (pkg / "module.py").write_text(
            "from mypkg import helper\n"
            "helper()\n",
        )

        # Build graph from the package directory
        graph = build_import_graph_from_directory(pkg)

        # Check that module.py's import of 'mypkg' resolved correctly
        module_path = (pkg / "module.py").resolve()
        init_path = (pkg / "__init__.py").resolve()

        # Find the edge from module.py importing from mypkg
        edge_to_init = None
        for edge in graph.get_imports(module_path):
            if edge.module_name == "mypkg":
                edge_to_init = edge
                break

        assert edge_to_init is not None, "Should find import edge for 'mypkg'"
        assert edge_to_init.imported == init_path, (
            f"'from mypkg import helper' should resolve to {init_path}, "
            f"got {edge_to_init.imported}"
        )


def test_package_directory_reexport_within_package():
    """Re-exports within a package should be detected when analyzing package dir.

    When pkg/module.py does `from pkg import helper`, and helper is defined in
    pkg/utils.py but re-exported via pkg/__init__.py, the re-export chain
    should be properly detected.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # Create a package
        pkg = root / "mypkg"
        pkg.mkdir()

        # mypkg/__init__.py re-exports helper from utils
        (pkg / "__init__.py").write_text(
            "from mypkg.utils import helper\n",
        )

        # mypkg/utils.py defines helper
        (pkg / "utils.py").write_text(
            "def helper(): pass\n",
        )

        # mypkg/consumer.py imports and uses helper from the package
        (pkg / "consumer.py").write_text(
            "from mypkg import helper\n"
            "helper()\n",
        )

        # Build and analyze
        graph = build_import_graph_from_directory(pkg)
        result = analyze_cross_file(graph)

        # __init__.py's helper import should NOT be unused (re-exported to consumer.py)
        init_unused = result.unused_imports.get((pkg / "__init__.py").resolve(), [])
        assert not any(imp.name == "helper" for imp in init_unused), (
            "helper should NOT be unused in __init__.py (re-exported to consumer.py)"
        )


def test_directory_mode_only_reports_files_in_scope():
    """When analyzing a directory, only files under that dir should be reported.

    The graph may include files discovered via imports (sibling packages),
    but unused imports should only be reported for files within the target dir.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # Create two sibling packages
        pkg_a = root / "pkg_a"
        pkg_b = root / "pkg_b"
        pkg_a.mkdir()
        pkg_b.mkdir()

        # pkg_a/__init__.py - has unused import
        (pkg_a / "__init__.py").write_text(
            "import os  # unused in pkg_a\n",
        )

        # pkg_a/module.py - imports from sibling pkg_b
        (pkg_a / "module.py").write_text(
            "from pkg_b import helper\n"
            "helper()\n",
        )

        # pkg_b/__init__.py - has unused import
        (pkg_b / "__init__.py").write_text(
            "import sys  # unused in pkg_b\n"
            "def helper(): pass\n",
        )

        # Analyze only pkg_a
        count, messages = check_cross_file(pkg_a)

        # Should only find unused import in pkg_a, not pkg_b
        output = "\n".join(messages)

        # pkg_a's unused 'os' should be reported
        assert "os" in output, "Should report unused 'os' from pkg_a"

        # pkg_b's unused 'sys' should NOT be reported (outside scope)
        # Check that pkg_b is not mentioned in file paths
        assert "pkg_b" not in output, (
            "Should NOT report unused imports from pkg_b (outside scope)"
        )


# =============================================================================
# Indirect import detection tests
# =============================================================================


def test_indirect_import_detected():
    """Should detect imports that go through re-exporters instead of sources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines CONFIG
        (root / "core.py").write_text("CONFIG = {}\n")

        # utils/__init__.py re-exports CONFIG from core.py
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from core import CONFIG\n")

        # app.py imports CONFIG from utils (indirect) instead of core (direct)
        (root / "app.py").write_text(
            "from utils import CONFIG\n" "print(CONFIG)\n",
        )

        graph = build_import_graph(root / "app.py")
        result = analyze_cross_file(graph, entry_point=root / "app.py")

        # Should detect the indirect import
        assert len(result.indirect_imports) == 1
        ind = result.indirect_imports[0]
        assert ind.file == root / "app.py"
        assert ind.name == "CONFIG"
        assert ind.current_source == utils / "__init__.py"
        assert ind.original_source == root / "core.py"
        assert ind.is_same_package is False


def test_indirect_import_multi_hop():
    """Should trace through multiple hops to find the original source."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines Helper
        (root / "core.py").write_text("class Helper: pass\n")

        # utils.py re-exports Helper from core
        (root / "utils.py").write_text("from core import Helper\n")

        # api.py re-exports Helper from utils
        (root / "api.py").write_text("from utils import Helper\n")

        # main.py imports Helper from api (3 hops from core)
        (root / "main.py").write_text(
            "from api import Helper\n" "h = Helper()\n",
        )

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # Should detect 2 indirect imports:
        # 1. api.py imports from utils.py (source is core.py)
        # 2. main.py imports from api.py (source is core.py)
        assert len(result.indirect_imports) == 2

        # All should trace back to core.py as the original source
        for ind in result.indirect_imports:
            assert ind.name == "Helper"
            assert ind.original_source == root / "core.py"

        # main.py's import should trace through api.py
        main_indirect = [i for i in result.indirect_imports if i.file == root / "main.py"]
        assert len(main_indirect) == 1
        assert main_indirect[0].current_source == root / "api.py"


def test_same_package_reexport_not_flagged_by_default():
    """Same-package re-exports (__init__.py re-exporting from submodule) should not be flagged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # pkg/__init__.py re-exports Foo from pkg/foo.py
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from pkg.foo import Foo\n")
        (pkg / "foo.py").write_text("class Foo: pass\n")

        # main.py imports Foo from pkg (this is the standard public API pattern)
        (root / "main.py").write_text(
            "from pkg import Foo\n" "f = Foo()\n",
        )

        graph = build_import_graph(root / "main.py")
        result = analyze_cross_file(graph, entry_point=root / "main.py")

        # Should NOT detect this as indirect (it's same-package re-export)
        assert len(result.indirect_imports) == 0


def test_same_package_reexport_flagged_with_strict_mode():
    """Same-package re-exports should be flagged when include_same_package_indirect=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # pkg/__init__.py re-exports Foo from pkg/foo.py
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from pkg.foo import Foo\n")
        (pkg / "foo.py").write_text("class Foo: pass\n")

        # main.py imports Foo from pkg
        (root / "main.py").write_text(
            "from pkg import Foo\n" "f = Foo()\n",
        )

        graph = build_import_graph(root / "main.py")
        # With include_same_package_indirect=True
        result = analyze_cross_file(
            graph,
            entry_point=root / "main.py",
            include_same_package_indirect=True,
        )

        # Should detect this as indirect in strict mode
        assert len(result.indirect_imports) == 1
        ind = result.indirect_imports[0]
        assert ind.name == "Foo"
        assert ind.is_same_package is True


def test_direct_import_not_flagged():
    """Direct imports (importing from the defining module) should not be flagged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines CONFIG
        (root / "core.py").write_text("CONFIG = {}\n")

        # app.py imports CONFIG directly from core
        (root / "app.py").write_text(
            "from core import CONFIG\n" "print(CONFIG)\n",
        )

        graph = build_import_graph(root / "app.py")
        result = analyze_cross_file(graph, entry_point=root / "app.py")

        # Should NOT detect any indirect imports
        assert len(result.indirect_imports) == 0


def test_cross_package_reexport_flagged():
    """Re-exports from different packages should always be flagged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # helpers.py defines helper
        (root / "helpers.py").write_text("helper = 'helper instance'\n")

        # utils/__init__.py re-exports helper from helpers (cross-package)
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from helpers import helper\n")

        # app.py imports helper from utils
        (root / "app.py").write_text(
            "from utils import helper\n" "print(helper)\n",
        )

        graph = build_import_graph(root / "app.py")
        result = analyze_cross_file(graph, entry_point=root / "app.py")

        # Should detect as indirect (cross-package re-export)
        assert len(result.indirect_imports) == 1
        ind = result.indirect_imports[0]
        assert ind.name == "helper"
        assert ind.is_same_package is False


def test_mixed_direct_and_indirect_imports():
    """Should only flag indirect imports, not direct ones from the same import."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # utils/__init__.py defines Client and re-exports helper
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text(
            "from helpers import helper\n"
            "class Client: pass\n",
        )

        # helpers.py defines helper
        (root / "helpers.py").write_text("helper = 'helper instance'\n")

        # app.py imports both Client (direct) and helper (indirect) from utils
        (root / "app.py").write_text(
            "from utils import helper, Client\n"
            "c = Client()\n"
            "print(helper)\n",
        )

        graph = build_import_graph(root / "app.py")
        result = analyze_cross_file(graph, entry_point=root / "app.py")

        # Should only flag helper as indirect, not Client
        assert len(result.indirect_imports) == 1
        ind = result.indirect_imports[0]
        assert ind.name == "helper"


def test_fix_indirect_imports():
    """Should rewrite indirect imports to use direct sources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines CONFIG
        (root / "core.py").write_text("CONFIG = {}\n")

        # utils/__init__.py re-exports CONFIG from core.py
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from core import CONFIG\n")

        # app.py imports CONFIG from utils (indirect)
        (root / "app.py").write_text(
            "from utils import CONFIG\n" "print(CONFIG)\n",
        )

        # Run with --fix-indirect-imports
        check_cross_file(root / "app.py", fix_indirect=True)

        # app.py should now import directly from core
        app_content = (root / "app.py").read_text()
        assert "from core import CONFIG" in app_content
        assert "from utils import CONFIG" not in app_content


def test_fix_indirect_imports_preserves_direct():
    """Should preserve direct imports when fixing indirect ones."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # helpers.py defines helper
        (root / "helpers.py").write_text("helper = 'helper instance'\n")

        # utils/__init__.py defines Client and re-exports helper
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text(
            "from helpers import helper\n"
            "class Client: pass\n",
        )

        # app.py imports both Client (direct) and helper (indirect)
        (root / "app.py").write_text(
            "from utils import helper, Client\n"
            "c = Client()\n"
            "print(helper)\n",
        )

        # Run with --fix-indirect-imports
        check_cross_file(root / "app.py", fix_indirect=True)

        # app.py should now have separate imports
        app_content = (root / "app.py").read_text()
        assert "from helpers import helper" in app_content
        assert "from utils import Client" in app_content
        # Should NOT have the combined import anymore
        assert "from utils import helper, Client" not in app_content
        assert "from utils import helper" not in app_content


def test_fix_indirect_and_fix_unused_cascade():
    """Should cascade: fix indirect, then re-export file is no longer traversed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines CONFIG
        (root / "core.py").write_text("CONFIG = {}\n")

        # utils/__init__.py re-exports CONFIG from core.py
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from core import CONFIG\n")

        # app.py imports CONFIG from utils (indirect)
        (root / "app.py").write_text(
            "from utils import CONFIG\n" "print(CONFIG)\n",
        )

        # First pass: fix indirect imports
        check_cross_file(root / "app.py", fix_indirect=True)

        # app.py now imports directly from core
        app_content = (root / "app.py").read_text()
        assert "from core import CONFIG" in app_content

        # Second pass: utils/__init__.py is no longer even in the graph
        # because nothing imports from it anymore
        graph = build_import_graph(root / "app.py")

        # utils/__init__.py should not be traversed anymore
        assert (utils / "__init__.py") not in graph.nodes, (
            "utils/__init__.py should no longer be in graph after indirect fix"
        )

        # Only app.py and core.py should be in the graph now
        assert len(graph.nodes) == 2
        assert (root / "app.py") in graph.nodes
        assert (root / "core.py") in graph.nodes


def test_fix_indirect_imports_with_strict_mode():
    """Should fix same-package re-exports when strict_indirect_imports=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # pkg/__init__.py re-exports Foo from pkg/foo.py (same-package re-export)
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from pkg.foo import Foo\n")
        (pkg / "foo.py").write_text("class Foo: pass\n")

        # main.py imports Foo from pkg (indirect, but same-package)
        (root / "main.py").write_text(
            "from pkg import Foo\n" "f = Foo()\n",
        )

        # Without strict mode, this should NOT be fixed
        check_cross_file(
            root / "main.py",
            fix_indirect=True,
            strict_indirect_imports=False,
        )

        # main.py should still import from pkg (not fixed)
        main_content = (root / "main.py").read_text()
        assert "from pkg import Foo" in main_content

        # Now with strict mode, it SHOULD be fixed
        check_cross_file(
            root / "main.py",
            fix_indirect=True,
            strict_indirect_imports=True,
        )

        # main.py should now import directly from pkg.foo
        main_content = (root / "main.py").read_text()
        assert "from pkg.foo import Foo" in main_content
        assert "from pkg import Foo" not in main_content


# =============================================================================
# Aliased import chain tests
# =============================================================================


def test_indirect_import_with_alias_in_reexporter():
    """Detect indirect imports where the re-exporter uses an alias."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines CONFIG
        (root / "core.py").write_text("CONFIG = {}\n")

        # utils/__init__.py re-exports CONFIG as CONF
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from core import CONFIG as CONF\n")

        # app.py imports CONF from utils (indirect)
        (root / "app.py").write_text(
            "from utils import CONF\n" "print(CONF)\n",
        )

        graph = build_import_graph(root / "app.py")
        result = analyze_cross_file(graph, entry_point=root / "app.py")

        # Should detect the indirect import
        assert len(result.indirect_imports) == 1
        ind = result.indirect_imports[0]
        assert ind.file == root / "app.py"
        assert ind.name == "CONF"  # Local name
        assert ind.original_name == "CONFIG"  # Original name in core.py
        assert ind.original_source == root / "core.py"


def test_fix_indirect_import_with_alias_preserves_local_name():
    """Fix should preserve local name when original source uses different name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines CONFIG
        (root / "core.py").write_text("CONFIG = {}\n")

        # utils/__init__.py re-exports CONFIG as CONF
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from core import CONFIG as CONF\n")

        # app.py imports CONF from utils
        (root / "app.py").write_text(
            "from utils import CONF\n" "print(CONF)\n",
        )

        # Run fix
        check_cross_file(root / "app.py", fix_indirect=True)

        # app.py should now import from core with alias
        app_content = (root / "app.py").read_text()
        assert "from core import CONFIG as CONF" in app_content
        assert "from utils import CONF" not in app_content


def test_fix_indirect_import_multi_hop_alias():
    """Fix should handle aliases through multiple hops."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # base.py defines SETTING
        (root / "base.py").write_text("SETTING = 'value'\n")

        # middle.py re-exports SETTING as CFG
        (root / "middle.py").write_text("from base import SETTING as CFG\n")

        # utils/__init__.py re-exports CFG as CONF
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from middle import CFG as CONF\n")

        # app.py imports CONF from utils
        (root / "app.py").write_text(
            "from utils import CONF\n" "print(CONF)\n",
        )

        # Run fix
        check_cross_file(root / "app.py", fix_indirect=True)

        # app.py should now import from base with alias preserving local name
        app_content = (root / "app.py").read_text()
        assert "from base import SETTING as CONF" in app_content
        assert "from utils import CONF" not in app_content


def test_indirect_import_no_alias_needed():
    """When original name matches local name, no alias should be added."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # core.py defines CONFIG
        (root / "core.py").write_text("CONFIG = {}\n")

        # utils/__init__.py re-exports CONFIG (no alias)
        utils = root / "utils"
        utils.mkdir()
        (utils / "__init__.py").write_text("from core import CONFIG\n")

        # app.py imports CONFIG from utils
        (root / "app.py").write_text(
            "from utils import CONFIG\n" "print(CONFIG)\n",
        )

        # Run fix
        check_cross_file(root / "app.py", fix_indirect=True)

        # app.py should import without alias (names match)
        app_content = (root / "app.py").read_text()
        assert "from core import CONFIG" in app_content
        assert "as CONFIG" not in app_content  # No alias needed
