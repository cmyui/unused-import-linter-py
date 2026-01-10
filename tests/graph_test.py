"""Tests for import graph construction (_graph.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from remove_unused_imports._graph import ImportGraph
from remove_unused_imports._graph import build_import_graph
from remove_unused_imports._graph import build_import_graph_from_directory

# =============================================================================
# ImportGraph tests
# =============================================================================


def test_import_graph_add_and_get_node():
    """Should add and retrieve nodes."""
    from remove_unused_imports._data import ModuleInfo

    graph = ImportGraph()
    path = Path("/test/module.py")
    info = ModuleInfo(
        file_path=path,
        module_name="module",
        is_package=False,
    )
    graph.add_node(info)

    assert path in graph.nodes
    assert graph.nodes[path] == info


def test_import_graph_add_and_get_edge():
    """Should add and retrieve edges."""
    from remove_unused_imports._data import ImportEdge

    graph = ImportGraph()
    importer = Path("/test/a.py")
    imported = Path("/test/b.py")
    edge = ImportEdge(
        importer=importer,
        imported=imported,
        module_name="b",
        names={"foo"},
        is_external=False,
    )
    graph.add_edge(edge)

    assert len(graph.edges) == 1
    assert graph.get_imports(importer) == [edge]
    assert graph.get_importers(imported) == [edge]


def test_import_graph_get_imports_empty():
    """Should return empty list for unknown files."""
    graph = ImportGraph()
    assert graph.get_imports(Path("/unknown.py")) == []


def test_import_graph_get_importers_empty():
    """Should return empty list for unknown files."""
    graph = ImportGraph()
    assert graph.get_importers(Path("/unknown.py")) == []


# =============================================================================
# Cycle detection tests
# =============================================================================


@pytest.fixture
def cyclic_project_dir():
    """Create a project with circular imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # Create a -> b -> c -> a cycle
        (root / "a.py").write_text("from b import x\n")
        (root / "b.py").write_text("from c import y\n")
        (root / "c.py").write_text("from a import z\n")

        yield root


def test_detect_cycle(cyclic_project_dir):
    """Should detect circular imports."""
    graph = build_import_graph(cyclic_project_dir / "a.py")
    cycles = graph.find_cycles()

    assert len(cycles) == 1
    cycle_names = {p.name for p in cycles[0]}
    assert cycle_names == {"a.py", "b.py", "c.py"}


def test_no_cycles():
    """Should return empty list when no cycles."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # No cycles: a -> b, a -> c
        (root / "a.py").write_text("import b\nimport c\n")
        (root / "b.py").write_text("# no imports\n")
        (root / "c.py").write_text("# no imports\n")

        graph = build_import_graph(root / "a.py")
        cycles = graph.find_cycles()
        assert cycles == []


# =============================================================================
# Topological order tests
# =============================================================================


def test_topological_basic_order():
    """Should return dependencies before dependents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # a imports b, b imports c
        (root / "a.py").write_text("import b\n")
        (root / "b.py").write_text("import c\n")
        (root / "c.py").write_text("# no imports\n")

        graph = build_import_graph(root / "a.py")
        order = graph.topological_order()
        names = [p.name for p in order]

        # c should come before b, b before a
        assert names.index("c.py") < names.index("b.py")
        assert names.index("b.py") < names.index("a.py")


# =============================================================================
# GraphBuilder tests
# =============================================================================


@pytest.fixture
def graph_builder_project_dir():
    """Create a test project for graph builder tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # Create structure:
        # main.py imports utils
        # utils.py imports typing
        # helpers.py (unreachable)

        (root / "main.py").write_text("from utils import helper\nhelper()\n")
        (root / "utils.py").write_text(
            "from typing import List\ndef helper() -> List[int]: return []\n",
        )
        (root / "helpers.py").write_text(
            "# This file is not reachable from main.py\n",
        )

        yield root


def test_graph_builder_entry_point_mode(graph_builder_project_dir):
    """Should only include files reachable from entry point."""
    graph = build_import_graph(graph_builder_project_dir / "main.py")

    file_names = {p.name for p in graph.nodes}
    assert "main.py" in file_names
    assert "utils.py" in file_names
    # helpers.py is not reachable from main.py
    assert "helpers.py" not in file_names


def test_graph_builder_directory_mode(graph_builder_project_dir):
    """Should include all Python files in directory mode."""
    graph = build_import_graph_from_directory(graph_builder_project_dir)

    file_names = {p.name for p in graph.nodes}
    assert "main.py" in file_names
    assert "utils.py" in file_names
    assert "helpers.py" in file_names


def test_graph_builder_module_info_populated(graph_builder_project_dir):
    """Should populate ModuleInfo correctly."""
    graph = build_import_graph(graph_builder_project_dir / "main.py")

    # Check main.py
    main_info = graph.nodes[graph_builder_project_dir / "main.py"]
    assert main_info.module_name == "main"
    assert not main_info.is_package
    assert len(main_info.imports) == 1
    assert main_info.imports[0].name == "helper"

    # Check utils.py
    utils_info = graph.nodes[graph_builder_project_dir / "utils.py"]
    assert utils_info.module_name == "utils"
    assert "helper" in utils_info.defined_names


def test_graph_builder_edges_created(graph_builder_project_dir):
    """Should create edges for imports."""
    graph = build_import_graph(graph_builder_project_dir / "main.py")

    # Find edge from main to utils
    main_imports = graph.get_imports(graph_builder_project_dir / "main.py")
    local_imports = [e for e in main_imports if not e.is_external]

    assert len(local_imports) == 1
    assert local_imports[0].imported == graph_builder_project_dir / "utils.py"
    assert "helper" in local_imports[0].names


def test_graph_builder_external_imports_tracked(graph_builder_project_dir):
    """Should track external imports."""
    graph = build_import_graph(graph_builder_project_dir / "main.py")

    utils_imports = graph.get_imports(graph_builder_project_dir / "utils.py")
    external_imports = [e for e in utils_imports if e.is_external]

    assert len(external_imports) == 1
    assert external_imports[0].module_name == "typing"
    assert "List" in external_imports[0].names


# =============================================================================
# Relative import tests
# =============================================================================


@pytest.fixture
def relative_import_package_dir():
    """Create a package with relative imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .utils import helper\n")
        (pkg / "utils.py").write_text("def helper(): pass\n")
        (pkg / "main.py").write_text("from . import utils\n")

        yield root


def test_relative_imports_resolved(relative_import_package_dir):
    """Should resolve relative imports correctly."""
    graph = build_import_graph(relative_import_package_dir / "pkg" / "main.py")

    main_imports = graph.get_imports(relative_import_package_dir / "pkg" / "main.py")

    # Should have resolved the relative import
    assert len(main_imports) == 1
    assert main_imports[0].imported == relative_import_package_dir / "pkg" / "__init__.py"


# =============================================================================
# Export (__all__) tests
# =============================================================================


def test_all_exports_detected():
    """Should detect names in __all__."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "module.py").write_text(
            "__all__ = ['foo', 'bar']\n" "def foo(): pass\n" "def bar(): pass\n",
        )

        graph = build_import_graph(root / "module.py")
        module_info = graph.nodes[root / "module.py"]

        assert module_info.exports == {"foo", "bar"}


def test_no_all_empty_exports():
    """Should have empty exports when no __all__."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "module.py").write_text("def foo(): pass\n")

        graph = build_import_graph(root / "module.py")
        module_info = graph.nodes[root / "module.py"]

        assert module_info.exports == set()


# =============================================================================
# Defined name tests
# =============================================================================


def test_function_names_detected():
    """Should detect function definitions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "module.py").write_text(
            "def foo(): pass\n" "async def bar(): pass\n",
        )

        graph = build_import_graph(root / "module.py")
        module_info = graph.nodes[root / "module.py"]

        assert "foo" in module_info.defined_names
        assert "bar" in module_info.defined_names


def test_class_names_detected():
    """Should detect class definitions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "module.py").write_text("class MyClass: pass\n")

        graph = build_import_graph(root / "module.py")
        module_info = graph.nodes[root / "module.py"]

        assert "MyClass" in module_info.defined_names


def test_variable_names_detected():
    """Should detect variable assignments."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        (root / "module.py").write_text("x = 1\n" "y: int = 2\n" "a, b = 3, 4\n")

        graph = build_import_graph(root / "module.py")
        module_info = graph.nodes[root / "module.py"]

        assert "x" in module_info.defined_names
        assert "y" in module_info.defined_names
        assert "a" in module_info.defined_names
        assert "b" in module_info.defined_names
