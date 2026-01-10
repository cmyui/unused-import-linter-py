"""Tests for cross-file import analysis (_cross_file.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from remove_unused_imports._cross_file import analyze_cross_file
from remove_unused_imports._graph import build_import_graph


class TestCrossFileAnalysis:
    """Tests for cross-file analysis."""

    @pytest.fixture
    def project_with_reexport(self):
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

    def test_reexported_import_not_unused(self, project_with_reexport):
        """Re-exported imports should NOT be marked as unused."""
        graph = build_import_graph(project_with_reexport / "main.py")
        result = analyze_cross_file(graph)

        # utils.py has List and Dict imports
        # List is re-exported to main.py, so only Dict should be unused
        utils_unused = result.unused_imports.get(project_with_reexport / "utils.py", [])
        unused_names = {imp.name for imp in utils_unused}

        assert "Dict" in unused_names
        assert "List" not in unused_names

    def test_implicit_reexport_detected(self, project_with_reexport):
        """Should detect imports re-exported without __all__."""
        graph = build_import_graph(project_with_reexport / "main.py")
        result = analyze_cross_file(graph)

        # List is re-exported but not in __all__
        assert len(result.implicit_reexports) == 1
        reexport = result.implicit_reexports[0]
        assert reexport.source_file == project_with_reexport / "utils.py"
        assert reexport.import_name == "List"
        assert project_with_reexport / "main.py" in reexport.used_by

    def test_external_usage_aggregated(self, project_with_reexport):
        """Should track which files use which external modules."""
        graph = build_import_graph(project_with_reexport / "main.py")
        result = analyze_cross_file(graph)

        assert "typing" in result.external_usage
        assert project_with_reexport / "utils.py" in result.external_usage["typing"]


class TestExplicitReexport:
    """Tests for explicit re-exports (in __all__)."""

    def test_explicit_reexport_not_flagged(self):
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


class TestNoReexports:
    """Tests for files with no re-exports."""

    def test_unused_import_when_no_reexport(self):
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


class TestCircularImports:
    """Tests for circular import detection."""

    def test_circular_import_detected(self):
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

    def test_no_circular_when_none(self):
        """Should report no circular imports when there are none."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            (root / "main.py").write_text("import utils\n")
            (root / "utils.py").write_text("# no imports\n")

            graph = build_import_graph(root / "main.py")
            result = analyze_cross_file(graph)

            assert result.circular_imports == []


class TestDefinedNamesNotReexport:
    """Test that defined names are not counted as re-exports."""

    def test_defined_name_not_reexport(self):
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


class TestMultipleReexports:
    """Test multiple levels of re-exports."""

    def test_chain_of_reexports(self):
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


class TestPartialReexport:
    """Test when some but not all imports are re-exported."""

    def test_partial_reexport(self):
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
