"""Tests for module resolution (_resolution.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from remove_unused_imports._resolution import ModuleResolver
from remove_unused_imports._resolution import get_external_modules


class TestGetExternalModules:
    """Tests for get_external_modules()."""

    def test_includes_stdlib_modules(self):
        """Should include common stdlib modules."""
        external = get_external_modules()
        stdlib_modules = ["os", "sys", "pathlib", "typing", "json", "re", "ast"]
        for mod in stdlib_modules:
            assert mod in external, f"{mod} should be in external modules"

    def test_includes_builtins(self):
        """Should include builtins module."""
        external = get_external_modules()
        assert "builtins" in external


class TestModuleResolver:
    """Tests for ModuleResolver class."""

    @pytest.fixture
    def project_dir(self):
        """Create a temporary project structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()  # Resolve symlinks

            # Create project structure:
            # project/
            #   main.py
            #   mypackage/
            #     __init__.py
            #     utils.py
            #     subpkg/
            #       __init__.py
            #       helper.py

            (root / "main.py").write_text("# entry point\n")

            pkg = root / "mypackage"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("# package init\n")
            (pkg / "utils.py").write_text("# utils module\n")

            subpkg = pkg / "subpkg"
            subpkg.mkdir()
            (subpkg / "__init__.py").write_text("# subpackage init\n")
            (subpkg / "helper.py").write_text("# helper module\n")

            yield root

    @pytest.fixture
    def resolver(self, project_dir):
        """Create resolver with project main.py as entry point."""
        return ModuleResolver(project_dir / "main.py")

    def test_source_root_is_entry_parent(self, resolver, project_dir):
        """Source root should be entry point's parent directory."""
        assert resolver.source_root == project_dir

    def test_resolve_absolute_package(self, resolver, project_dir):
        """Should resolve top-level package to __init__.py."""
        result = resolver.resolve_import("mypackage", project_dir / "main.py")
        assert result == project_dir / "mypackage" / "__init__.py"

    def test_resolve_absolute_module(self, resolver, project_dir):
        """Should resolve module in package."""
        result = resolver.resolve_import("mypackage.utils", project_dir / "main.py")
        assert result == project_dir / "mypackage" / "utils.py"

    def test_resolve_absolute_subpackage(self, resolver, project_dir):
        """Should resolve subpackage to __init__.py."""
        result = resolver.resolve_import("mypackage.subpkg", project_dir / "main.py")
        assert result == project_dir / "mypackage" / "subpkg" / "__init__.py"

    def test_resolve_absolute_nested_module(self, resolver, project_dir):
        """Should resolve deeply nested module."""
        result = resolver.resolve_import(
            "mypackage.subpkg.helper", project_dir / "main.py",
        )
        assert result == project_dir / "mypackage" / "subpkg" / "helper.py"

    def test_resolve_external_returns_none(self, resolver, project_dir):
        """Should return None for external (stdlib) modules."""
        result = resolver.resolve_import("os", project_dir / "main.py")
        assert result is None

    def test_resolve_nonexistent_returns_none(self, resolver, project_dir):
        """Should return None for nonexistent modules."""
        result = resolver.resolve_import("nonexistent_xyz", project_dir / "main.py")
        assert result is None

    def test_is_external_stdlib(self, resolver):
        """Should detect stdlib modules as external."""
        assert resolver.is_external("os")
        assert resolver.is_external("sys")
        assert resolver.is_external("typing")
        assert resolver.is_external("os.path")

    def test_is_external_nonexistent_not_external(self, resolver):
        """Nonexistent modules should not be marked as external."""
        assert not resolver.is_external("nonexistent_xyz_123")


class TestRelativeImports:
    """Tests for relative import resolution."""

    @pytest.fixture
    def project_dir(self):
        """Create a project with relative imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            # project/
            #   pkg/
            #     __init__.py
            #     module_a.py
            #     module_b.py
            #     sub/
            #       __init__.py
            #       module_c.py

            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "module_a.py").write_text("")
            (pkg / "module_b.py").write_text("")

            sub = pkg / "sub"
            sub.mkdir()
            (sub / "__init__.py").write_text("")
            (sub / "module_c.py").write_text("")

            yield root

    @pytest.fixture
    def resolver(self, project_dir):
        """Create resolver."""
        return ModuleResolver(project_dir / "entry.py")

    def test_resolve_relative_level_1(self, resolver, project_dir):
        """from . import module_b (from module_a)."""
        from_file = project_dir / "pkg" / "module_a.py"
        result = resolver.resolve_import("module_b", from_file, level=1)
        assert result == project_dir / "pkg" / "module_b.py"

    def test_resolve_relative_level_1_init(self, resolver, project_dir):
        """from . import (empty) should return __init__.py."""
        from_file = project_dir / "pkg" / "module_a.py"
        result = resolver.resolve_import("", from_file, level=1)
        assert result == project_dir / "pkg" / "__init__.py"

    def test_resolve_relative_level_2(self, resolver, project_dir):
        """from .. import module_a (from sub/module_c.py)."""
        from_file = project_dir / "pkg" / "sub" / "module_c.py"
        result = resolver.resolve_import("module_a", from_file, level=2)
        assert result == project_dir / "pkg" / "module_a.py"

    def test_resolve_relative_subpackage(self, resolver, project_dir):
        """from .sub import module_c (from module_a)."""
        from_file = project_dir / "pkg" / "module_a.py"
        result = resolver.resolve_import("sub.module_c", from_file, level=1)
        assert result == project_dir / "pkg" / "sub" / "module_c.py"


class TestGetModuleName:
    """Tests for get_module_name()."""

    @pytest.fixture
    def project_dir(self):
        """Create a project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()

            pkg = root / "mypackage"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "utils.py").write_text("")

            sub = pkg / "sub"
            sub.mkdir()
            (sub / "__init__.py").write_text("")
            (sub / "module.py").write_text("")

            yield root

    @pytest.fixture
    def resolver(self, project_dir):
        """Create resolver."""
        return ModuleResolver(project_dir / "main.py")

    def test_module_name_for_module(self, resolver, project_dir):
        """Should return dotted module name for .py file."""
        path = project_dir / "mypackage" / "utils.py"
        assert resolver.get_module_name(path) == "mypackage.utils"

    def test_module_name_for_package(self, resolver, project_dir):
        """Should return package name for __init__.py."""
        path = project_dir / "mypackage" / "__init__.py"
        assert resolver.get_module_name(path) == "mypackage"

    def test_module_name_for_nested(self, resolver, project_dir):
        """Should return full dotted name for nested module."""
        path = project_dir / "mypackage" / "sub" / "module.py"
        assert resolver.get_module_name(path) == "mypackage.sub.module"

    def test_module_name_for_nested_package(self, resolver, project_dir):
        """Should return full dotted name for nested package."""
        path = project_dir / "mypackage" / "sub" / "__init__.py"
        assert resolver.get_module_name(path) == "mypackage.sub"


class TestPythonPath:
    """Tests for PYTHONPATH handling."""

    @pytest.fixture
    def project_dirs(self):
        """Create two separate directories to simulate PYTHONPATH."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                root1 = Path(tmpdir1).resolve()
                root2 = Path(tmpdir2).resolve()

                # root1/main.py
                (root1 / "main.py").write_text("")

                # root2/extra_pkg/__init__.py
                pkg2 = root2 / "extra_pkg"
                pkg2.mkdir()
                (pkg2 / "__init__.py").write_text("")
                (pkg2 / "module.py").write_text("")

                yield root1, root2

    def test_pythonpath_resolution(self, project_dirs, monkeypatch):
        """Should resolve modules from PYTHONPATH."""
        root1, root2 = project_dirs
        monkeypatch.setenv("PYTHONPATH", str(root2))

        resolver = ModuleResolver(root1 / "main.py")

        # Should find extra_pkg from PYTHONPATH
        result = resolver.resolve_import("extra_pkg", root1 / "main.py")
        assert result == root2 / "extra_pkg" / "__init__.py"

        result = resolver.resolve_import("extra_pkg.module", root1 / "main.py")
        assert result == root2 / "extra_pkg" / "module.py"


class TestCaching:
    """Tests for resolution caching."""

    @pytest.fixture
    def project_dir(self):
        """Create a simple project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            (root / "main.py").write_text("")
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            yield root

    def test_cache_hit(self, project_dir):
        """Should cache resolved paths."""
        resolver = ModuleResolver(project_dir / "main.py")
        from_file = project_dir / "main.py"

        # First call
        result1 = resolver.resolve_import("pkg", from_file)
        # Second call should use cache
        result2 = resolver.resolve_import("pkg", from_file)

        assert result1 == result2
        # Cache should have an entry
        assert len(resolver._cache) > 0


class TestLocalOverridesExternal:
    """Test that local modules take precedence over installed packages."""

    @pytest.fixture
    def project_dir(self):
        """Create a project with a module that shadows a stdlib name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            (root / "main.py").write_text("")
            # Create a local 'json' module (shadows stdlib)
            (root / "json.py").write_text("# local json module\n")
            yield root

    def test_local_shadows_stdlib(self, project_dir):
        """Local module should take precedence over stdlib."""
        resolver = ModuleResolver(project_dir / "main.py")

        # json is in stdlib, but we have a local json.py
        result = resolver.resolve_import("json", project_dir / "main.py")

        # Should resolve to local, not return None for external
        assert result == project_dir / "json.py"
