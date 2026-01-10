"""Tests for import graph construction (_graph.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from remove_unused_imports._graph import ImportGraph
from remove_unused_imports._graph import build_import_graph
from remove_unused_imports._graph import build_import_graph_from_directory


class TestImportGraph:
    """Tests for ImportGraph class."""

    def test_add_and_get_node(self):
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

    def test_add_and_get_edge(self):
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

    def test_get_imports_empty(self):
        """Should return empty list for unknown files."""
        graph = ImportGraph()
        assert graph.get_imports(Path("/unknown.py")) == []

    def test_get_importers_empty(self):
        """Should return empty list for unknown files."""
        graph = ImportGraph()
        assert graph.get_importers(Path("/unknown.py")) == []


class TestCycleDetection:
    """Tests for cycle detection."""

    @pytest.fixture
    def project_dir(self):
        """Create a project with circular imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            # Create a -> b -> c -> a cycle
            (root / "a.py").write_text("from b import x\n")
            (root / "b.py").write_text("from c import y\n")
            (root / "c.py").write_text("from a import z\n")

            yield root

    def test_detect_cycle(self, project_dir):
        """Should detect circular imports."""
        graph = build_import_graph(project_dir / "a.py")
        cycles = graph.find_cycles()

        assert len(cycles) == 1
        cycle_names = {p.name for p in cycles[0]}
        assert cycle_names == {"a.py", "b.py", "c.py"}

    def test_no_cycles(self):
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


class TestTopologicalOrder:
    """Tests for topological ordering."""

    def test_basic_order(self):
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


class TestGraphBuilder:
    """Tests for GraphBuilder class."""

    @pytest.fixture
    def project_dir(self):
        """Create a test project."""
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

    def test_entry_point_mode(self, project_dir):
        """Should only include files reachable from entry point."""
        graph = build_import_graph(project_dir / "main.py")

        file_names = {p.name for p in graph.nodes}
        assert "main.py" in file_names
        assert "utils.py" in file_names
        # helpers.py is not reachable from main.py
        assert "helpers.py" not in file_names

    def test_directory_mode(self, project_dir):
        """Should include all Python files in directory mode."""
        graph = build_import_graph_from_directory(project_dir)

        file_names = {p.name for p in graph.nodes}
        assert "main.py" in file_names
        assert "utils.py" in file_names
        assert "helpers.py" in file_names

    def test_module_info_populated(self, project_dir):
        """Should populate ModuleInfo correctly."""
        graph = build_import_graph(project_dir / "main.py")

        # Check main.py
        main_info = graph.nodes[project_dir / "main.py"]
        assert main_info.module_name == "main"
        assert not main_info.is_package
        assert len(main_info.imports) == 1
        assert main_info.imports[0].name == "helper"

        # Check utils.py
        utils_info = graph.nodes[project_dir / "utils.py"]
        assert utils_info.module_name == "utils"
        assert "helper" in utils_info.defined_names

    def test_edges_created(self, project_dir):
        """Should create edges for imports."""
        graph = build_import_graph(project_dir / "main.py")

        # Find edge from main to utils
        main_imports = graph.get_imports(project_dir / "main.py")
        local_imports = [e for e in main_imports if not e.is_external]

        assert len(local_imports) == 1
        assert local_imports[0].imported == project_dir / "utils.py"
        assert "helper" in local_imports[0].names

    def test_external_imports_tracked(self, project_dir):
        """Should track external imports."""
        graph = build_import_graph(project_dir / "main.py")

        utils_imports = graph.get_imports(project_dir / "utils.py")
        external_imports = [e for e in utils_imports if e.is_external]

        assert len(external_imports) == 1
        assert external_imports[0].module_name == "typing"
        assert "List" in external_imports[0].names


class TestRelativeImports:
    """Tests for relative import handling in graph."""

    @pytest.fixture
    def package_dir(self):
        """Create a package with relative imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("from .utils import helper\n")
            (pkg / "utils.py").write_text("def helper(): pass\n")
            (pkg / "main.py").write_text("from . import utils\n")

            yield root

    def test_relative_imports_resolved(self, package_dir):
        """Should resolve relative imports correctly."""
        graph = build_import_graph(package_dir / "pkg" / "main.py")

        main_imports = graph.get_imports(package_dir / "pkg" / "main.py")

        # Should have resolved the relative import
        assert len(main_imports) == 1
        assert main_imports[0].imported == package_dir / "pkg" / "__init__.py"


class TestExports:
    """Tests for __all__ export detection."""

    def test_all_exports_detected(self):
        """Should detect names in __all__."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            (root / "module.py").write_text(
                "__all__ = ['foo', 'bar']\n" "def foo(): pass\n" "def bar(): pass\n",
            )

            graph = build_import_graph(root / "module.py")
            module_info = graph.nodes[root / "module.py"]

            assert module_info.exports == {"foo", "bar"}

    def test_no_all_empty_exports(self):
        """Should have empty exports when no __all__."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            (root / "module.py").write_text("def foo(): pass\n")

            graph = build_import_graph(root / "module.py")
            module_info = graph.nodes[root / "module.py"]

            assert module_info.exports == set()


class TestDefinedNames:
    """Tests for defined name detection."""

    def test_function_names_detected(self):
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

    def test_class_names_detected(self):
        """Should detect class definitions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            (root / "module.py").write_text("class MyClass: pass\n")

            graph = build_import_graph(root / "module.py")
            module_info = graph.nodes[root / "module.py"]

            assert "MyClass" in module_info.defined_names

    def test_variable_names_detected(self):
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
