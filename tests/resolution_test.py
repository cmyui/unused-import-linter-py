"""Tests for module resolution (_resolution.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from remove_unused_imports._resolution import ModuleResolver
from remove_unused_imports._resolution import get_external_modules

# =============================================================================
# get_external_modules tests
# =============================================================================


def test_external_modules_includes_stdlib():
    """Should include common stdlib modules."""
    external = get_external_modules()
    stdlib_modules = ["os", "sys", "pathlib", "typing", "json", "re", "ast"]
    for mod in stdlib_modules:
        assert mod in external, f"{mod} should be in external modules"


def test_external_modules_includes_builtins():
    """Should include builtins module."""
    external = get_external_modules()
    assert "builtins" in external


# =============================================================================
# ModuleResolver tests
# =============================================================================


@pytest.fixture
def resolver_project_dir():
    """Create a temporary project structure for resolver tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

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


def test_resolver_source_root_is_entry_parent(resolver_project_dir):
    """Source root should be entry point's parent directory."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    assert resolver.source_root == resolver_project_dir


def test_resolver_resolve_absolute_package(resolver_project_dir):
    """Should resolve top-level package to __init__.py."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    result = resolver.resolve_import("mypackage", resolver_project_dir / "main.py")
    assert result == resolver_project_dir / "mypackage" / "__init__.py"


def test_resolver_resolve_absolute_module(resolver_project_dir):
    """Should resolve module in package."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    result = resolver.resolve_import(
        "mypackage.utils", resolver_project_dir / "main.py",
    )
    assert result == resolver_project_dir / "mypackage" / "utils.py"


def test_resolver_resolve_absolute_subpackage(resolver_project_dir):
    """Should resolve subpackage to __init__.py."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    result = resolver.resolve_import(
        "mypackage.subpkg", resolver_project_dir / "main.py",
    )
    assert result == resolver_project_dir / "mypackage" / "subpkg" / "__init__.py"


def test_resolver_resolve_absolute_nested_module(resolver_project_dir):
    """Should resolve deeply nested module."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    result = resolver.resolve_import(
        "mypackage.subpkg.helper", resolver_project_dir / "main.py",
    )
    assert result == resolver_project_dir / "mypackage" / "subpkg" / "helper.py"


def test_resolver_resolve_external_returns_none(resolver_project_dir):
    """Should return None for external (stdlib) modules."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    result = resolver.resolve_import("os", resolver_project_dir / "main.py")
    assert result is None


def test_resolver_resolve_nonexistent_returns_none(resolver_project_dir):
    """Should return None for nonexistent modules."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    result = resolver.resolve_import(
        "nonexistent_xyz", resolver_project_dir / "main.py",
    )
    assert result is None


def test_resolver_is_external_stdlib(resolver_project_dir):
    """Should detect stdlib modules as external."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    assert resolver.is_external("os")
    assert resolver.is_external("sys")
    assert resolver.is_external("typing")
    assert resolver.is_external("os.path")


def test_resolver_is_external_nonexistent_not_external(resolver_project_dir):
    """Nonexistent modules should not be marked as external."""
    resolver = ModuleResolver(resolver_project_dir / "main.py")
    assert not resolver.is_external("nonexistent_xyz_123")


# =============================================================================
# Relative import tests
# =============================================================================


@pytest.fixture
def relative_import_project_dir():
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


def test_resolve_relative_level_1(relative_import_project_dir):
    """from . import module_b (from module_a)."""
    resolver = ModuleResolver(relative_import_project_dir / "entry.py")
    from_file = relative_import_project_dir / "pkg" / "module_a.py"
    result = resolver.resolve_import("module_b", from_file, level=1)
    assert result == relative_import_project_dir / "pkg" / "module_b.py"


def test_resolve_relative_level_1_init(relative_import_project_dir):
    """from . import (empty) should return __init__.py."""
    resolver = ModuleResolver(relative_import_project_dir / "entry.py")
    from_file = relative_import_project_dir / "pkg" / "module_a.py"
    result = resolver.resolve_import("", from_file, level=1)
    assert result == relative_import_project_dir / "pkg" / "__init__.py"


def test_resolve_relative_level_2(relative_import_project_dir):
    """from .. import module_a (from sub/module_c.py)."""
    resolver = ModuleResolver(relative_import_project_dir / "entry.py")
    from_file = relative_import_project_dir / "pkg" / "sub" / "module_c.py"
    result = resolver.resolve_import("module_a", from_file, level=2)
    assert result == relative_import_project_dir / "pkg" / "module_a.py"


def test_resolve_relative_subpackage(relative_import_project_dir):
    """from .sub import module_c (from module_a)."""
    resolver = ModuleResolver(relative_import_project_dir / "entry.py")
    from_file = relative_import_project_dir / "pkg" / "module_a.py"
    result = resolver.resolve_import("sub.module_c", from_file, level=1)
    assert result == relative_import_project_dir / "pkg" / "sub" / "module_c.py"


# =============================================================================
# get_module_name tests
# =============================================================================


@pytest.fixture
def module_name_project_dir():
    """Create a project for module name tests."""
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


def test_module_name_for_module(module_name_project_dir):
    """Should return dotted module name for .py file."""
    resolver = ModuleResolver(module_name_project_dir / "main.py")
    path = module_name_project_dir / "mypackage" / "utils.py"
    assert resolver.get_module_name(path) == "mypackage.utils"


def test_module_name_for_package(module_name_project_dir):
    """Should return package name for __init__.py."""
    resolver = ModuleResolver(module_name_project_dir / "main.py")
    path = module_name_project_dir / "mypackage" / "__init__.py"
    assert resolver.get_module_name(path) == "mypackage"


def test_module_name_for_nested(module_name_project_dir):
    """Should return full dotted name for nested module."""
    resolver = ModuleResolver(module_name_project_dir / "main.py")
    path = module_name_project_dir / "mypackage" / "sub" / "module.py"
    assert resolver.get_module_name(path) == "mypackage.sub.module"


def test_module_name_for_nested_package(module_name_project_dir):
    """Should return full dotted name for nested package."""
    resolver = ModuleResolver(module_name_project_dir / "main.py")
    path = module_name_project_dir / "mypackage" / "sub" / "__init__.py"
    assert resolver.get_module_name(path) == "mypackage.sub"


# =============================================================================
# PYTHONPATH tests
# =============================================================================


def test_pythonpath_resolution(monkeypatch):
    """Should resolve modules from PYTHONPATH."""
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

            monkeypatch.setenv("PYTHONPATH", str(root2))

            resolver = ModuleResolver(root1 / "main.py")

            # Should find extra_pkg from PYTHONPATH
            result = resolver.resolve_import("extra_pkg", root1 / "main.py")
            assert result == root2 / "extra_pkg" / "__init__.py"

            result = resolver.resolve_import("extra_pkg.module", root1 / "main.py")
            assert result == root2 / "extra_pkg" / "module.py"


# =============================================================================
# Caching tests
# =============================================================================


def test_resolver_cache_hit():
    """Should cache resolved paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        (root / "main.py").write_text("")
        pkg = root / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        resolver = ModuleResolver(root / "main.py")
        from_file = root / "main.py"

        # First call
        result1 = resolver.resolve_import("pkg", from_file)
        # Second call should use cache
        result2 = resolver.resolve_import("pkg", from_file)

        assert result1 == result2
        # Cache should have an entry
        assert len(resolver._cache) > 0


# =============================================================================
# Local overrides external tests
# =============================================================================


def test_local_shadows_stdlib():
    """Local module should take precedence over stdlib."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        (root / "main.py").write_text("")
        # Create a local 'json' module (shadows stdlib)
        (root / "json.py").write_text("# local json module\n")

        resolver = ModuleResolver(root / "main.py")

        # json is in stdlib, but we have a local json.py
        result = resolver.resolve_import("json", root / "main.py")

        # Should resolve to local, not return None for external
        assert result == root / "json.py"
