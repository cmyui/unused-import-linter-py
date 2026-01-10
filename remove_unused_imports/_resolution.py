"""Module resolution - mirrors Python's import system."""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path


def get_external_modules() -> set[str]:
    """Get set of known external (stdlib + installed) module names.

    Uses multiple strategies to build a comprehensive list:
    1. sys.stdlib_module_names (Python 3.10+) - authoritative list
    2. Filesystem scan of stdlib directory (fallback for older Python)
    3. Hardcoded list of common modules (catches built-in modules compiled
       into the interpreter that don't exist as files, e.g., sys, builtins)
    4. Installed packages from importlib.metadata
    """
    external: set[str] = set()

    # Strategy 1: sys.stdlib_module_names (Python 3.10+)
    # This is the authoritative source when available
    if hasattr(sys, "stdlib_module_names"):
        external.update(sys.stdlib_module_names)
    else:
        # Strategy 2: Filesystem scan (fallback for Python < 3.10)
        # Note: This only finds modules that exist as files/packages in the
        # stdlib directory. Built-in modules compiled into the interpreter
        # (like sys, builtins) won't be found here - they're handled by
        # the hardcoded list below.
        import sysconfig

        stdlib_path = Path(sysconfig.get_path("stdlib"))
        if stdlib_path.exists():
            for item in stdlib_path.iterdir():
                if item.suffix == ".py":
                    external.add(item.stem)
                elif item.is_dir() and (item / "__init__.py").exists():
                    external.add(item.name)

    # Strategy 3: Hardcoded list of common built-in modules
    # These modules are compiled into the Python interpreter and may not
    # exist as separate files in the stdlib path. This list ensures they're
    # recognized as external even on Python < 3.10 where the filesystem
    # scan would miss them.
    external.update({
        "builtins",
        "sys",
        "os",
        "typing",
        "collections",
        "functools",
        "itertools",
        "pathlib",
        "dataclasses",
        "enum",
        "abc",
        "re",
        "json",
        "datetime",
        "time",
        "math",
        "random",
        "io",
        "copy",
        "pickle",
        "hashlib",
        "base64",
        "struct",
        "logging",
        "warnings",
        "contextlib",
        "importlib",
        "inspect",
        "ast",
        "types",
        "typing_extensions",
    })

    # Strategy 4: Installed packages (from importlib.metadata)
    # Discovers third-party packages installed in the environment
    try:
        from importlib.metadata import distributions

        for dist in distributions():
            # Get the top-level package names
            if dist.files:
                top_levels: set[str] = set()
                for file in dist.files:
                    parts = str(file).split("/")
                    if parts[0].endswith(".py"):
                        top_levels.add(parts[0][:-3])
                    elif len(parts) > 1 and not parts[0].endswith(".dist-info"):
                        top_levels.add(parts[0])
                external.update(top_levels)
    except ImportError:
        pass

    return external


class ModuleResolver:
    """Resolve import statements to file paths.

    Mirrors Python's import system:
    - Entry point's parent directory is the source root (like sys.path[0])
    - Respects PYTHONPATH environment variable
    """

    def __init__(self, entry_point: Path) -> None:
        self.entry_point = entry_point.resolve()
        self.source_root = self.entry_point.parent
        self.pythonpath = self._parse_pythonpath()
        self.external_modules = get_external_modules()

        # Cache for resolved modules
        self._cache: dict[tuple[str, Path, int], Path | None] = {}

    def _parse_pythonpath(self) -> list[Path]:
        """Parse PYTHONPATH environment variable."""
        pythonpath_str = os.environ.get("PYTHONPATH", "")
        if not pythonpath_str:
            return []

        paths: list[Path] = []
        for p in pythonpath_str.split(os.pathsep):
            path = Path(p).resolve()
            if path.exists() and path.is_dir():
                paths.append(path)
        return paths

    def _get_search_paths(self) -> list[Path]:
        """Get ordered list of paths to search for modules."""
        # Order matters: source root first, then PYTHONPATH
        paths = [self.source_root]
        paths.extend(self.pythonpath)
        return paths

    def is_external(self, module_name: str) -> bool:
        """Check if a module is external (stdlib or installed package)."""
        # Get the top-level module name
        top_level = module_name.split(".")[0]
        return top_level in self.external_modules

    def resolve_import(
        self,
        module_name: str,
        from_file: Path,
        level: int = 0,
    ) -> Path | None:
        """Resolve an import statement to a file path.

        Args:
            module_name: The module being imported (e.g., "os.path" or "utils")
            from_file: The file containing the import statement
            level: Number of dots for relative imports (0 = absolute)

        Returns:
            Path to the resolved module file, or None if external/not found.
        """
        cache_key = (module_name, from_file, level)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = self._resolve_import_uncached(module_name, from_file, level)
        self._cache[cache_key] = result
        return result

    def _resolve_import_uncached(
        self,
        module_name: str,
        from_file: Path,
        level: int,
    ) -> Path | None:
        """Actual resolution logic (uncached)."""
        from_file = from_file.resolve()

        if level > 0:
            # Relative import
            return self._resolve_relative(module_name, from_file, level)
        else:
            # Absolute import
            # Try to resolve locally first (like Python's sys.path[0] priority)
            local_result = self._resolve_absolute(module_name)
            if local_result is not None:
                return local_result

            # Not found locally - check if it's an external module
            # (stdlib or installed package)
            if self.is_external(module_name):
                return None

            # Neither local nor external - not found
            return None

    def _resolve_relative(
        self,
        module_name: str,
        from_file: Path,
        level: int,
    ) -> Path | None:
        """Resolve a relative import (from . import x, from ..parent import y)."""
        # Start from the directory containing the importing file
        current = from_file.parent

        # Go up 'level' directories (level=1 means current package, level=2 means parent, etc.)
        for _ in range(level - 1):
            current = current.parent
            # Check if we've gone above the source root
            # (mirrors Python's "attempted relative import beyond top-level package")
            try:
                current.relative_to(self.source_root)
            except ValueError:
                warnings.warn(
                    f"Relative import with level={level} in {from_file} "
                    f"goes beyond source root (this would raise ImportError at runtime)",
                )
                return None

        # If there's a module name, resolve it relative to current
        if module_name:
            return self._find_module_at(current, module_name)
        else:
            # `from . import x` - current package's __init__.py
            init_file = current / "__init__.py"
            if init_file.exists():
                return init_file
            return None

    def _resolve_absolute(self, module_name: str) -> Path | None:
        """Resolve an absolute import."""
        for search_path in self._get_search_paths():
            result = self._find_module_at(search_path, module_name)
            if result is not None:
                return result
        return None

    def _find_module_at(self, base: Path, module_name: str) -> Path | None:
        """Find a module starting from a base path.

        Handles dotted module names like "package.subpackage.module".
        """
        parts = module_name.split(".")
        current = base

        for i, part in enumerate(parts):
            # Try as a package (directory with __init__.py)
            package_path = current / part
            init_file = package_path / "__init__.py"

            if package_path.is_dir():
                if i == len(parts) - 1:
                    # Last part - could be package or module
                    if init_file.exists():
                        return init_file
                    # Check for module file
                    module_file = current / f"{part}.py"
                    if module_file.exists():
                        return module_file
                    # Package without __init__.py (namespace package) - skip
                    return None
                else:
                    # Not last part - must be a package
                    if init_file.exists():
                        current = package_path
                    else:
                        # Namespace package - continue searching
                        current = package_path
            else:
                # Try as a module file
                module_file = current / f"{part}.py"
                if module_file.exists():
                    if i == len(parts) - 1:
                        return module_file
                    else:
                        # Can't have submodules of a .py file
                        return None
                else:
                    return None

        return None

    def get_module_name(self, file_path: Path) -> str:
        """Get the fully-qualified module name for a file path."""
        file_path = file_path.resolve()

        # Find which search path contains this file
        for search_path in self._get_search_paths():
            try:
                relative = file_path.relative_to(search_path)
            except ValueError:
                continue

            # Convert path to module name
            parts = list(relative.parts)

            # Remove .py extension from last part
            if parts and parts[-1].endswith(".py"):
                parts[-1] = parts[-1][:-3]

            # Remove __init__ (it's implied for packages)
            if parts and parts[-1] == "__init__":
                parts.pop()

            if parts:
                return ".".join(parts)

        # Fallback: just use the file stem
        return file_path.stem
