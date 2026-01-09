from __future__ import annotations

import ast

from remove_unused_imports._data import ImportInfo


class ImportExtractor(ast.NodeVisitor):
    """Extract all imports from an AST."""

    def __init__(self) -> None:
        self.imports: list[ImportInfo] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            # For 'import X.Y.Z', only 'X' is bound in the local namespace
            # For 'import X.Y.Z as W', 'W' is bound
            if alias.asname:
                name = alias.asname
            else:
                # Only the top-level name is bound
                name = alias.name.split(".")[0]

            self.imports.append(
                ImportInfo(
                    name=name,
                    module="",
                    original_name=alias.name,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or 0,
                    is_from_import=False,
                    full_node_lineno=node.lineno,
                    full_node_end_lineno=node.end_lineno or node.lineno,
                ),
            )
        self.generic_visit(node)

    def visit_FromImport(self, node: ast.ImportFrom) -> None:
        module = node.module or ""

        # Skip __future__ imports - they have side effects and are never "unused"
        if module == "__future__":
            return

        for alias in node.names:
            if alias.name == "*":
                # Star imports can't be analyzed for unused names
                continue

            name = alias.asname if alias.asname else alias.name
            self.imports.append(
                ImportInfo(
                    name=name,
                    module=module,
                    original_name=alias.name,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or 0,
                    is_from_import=True,
                    full_node_lineno=node.lineno,
                    full_node_end_lineno=node.end_lineno or node.lineno,
                ),
            )
        self.generic_visit(node)

    # Alias for the actual AST node name
    visit_ImportFrom = visit_FromImport


class NameUsageCollector(ast.NodeVisitor):
    """Collect all name usages in the code, excluding import statements."""

    def __init__(self) -> None:
        self.used_names: set[str] = set()
        self._in_import = False

    def visit_Import(self, node: ast.Import) -> None:
        # Don't count names in import statements as usage
        pass

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Don't count names in import statements as usage
        pass

    def visit_Name(self, node: ast.Name) -> None:
        # Only count Load contexts as usages, not Store (assignment targets)
        # Store contexts: x = ..., for x in ..., with ... as x, except ... as x
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # For attribute access like 'os.path', we need to track 'os'
        # Only count Load contexts (reading), not Store (assignment targets)
        if not isinstance(node.ctx, ast.Load):
            self.generic_visit(node)
            return

        # Walk up to find the root name
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
            self.used_names.add(current.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Check decorators for name usage
        for decorator in node.decorator_list:
            self.visit(decorator)
        # Check annotations
        if node.returns:
            self.visit(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation:
                self.visit(arg.annotation)
        if node.args.vararg and node.args.vararg.annotation:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            self.visit(node.args.kwarg.annotation)
        # Check default argument values
        for default in node.args.defaults:
            self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default is not None:
                self.visit(kw_default)
        # Visit body
        for child in node.body:
            self.visit(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Same logic as FunctionDef
        for decorator in node.decorator_list:
            self.visit(decorator)
        if node.returns:
            self.visit(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation:
                self.visit(arg.annotation)
        if node.args.vararg and node.args.vararg.annotation:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            self.visit(node.args.kwarg.annotation)
        # Check default argument values
        for default in node.args.defaults:
            self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default is not None:
                self.visit(kw_default)
        for child in node.body:
            self.visit(child)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Check decorators and base classes
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        # Visit body
        for child in node.body:
            self.visit(child)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Handle annotated assignments: x: Type = value
        self.visit(node.annotation)
        if node.value:
            self.visit(node.value)
        self.visit(node.target)


class StringAnnotationVisitor(ast.NodeVisitor):
    """Extract names from string annotations (forward references)."""

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            # Try to parse the string as a type annotation
            try:
                parsed = ast.parse(node.value, mode="eval")
                collector = NameUsageCollector()
                collector.visit(parsed)
                self.used_names.update(collector.used_names)
            except SyntaxError:
                pass
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # Handle things like Optional["ClassName"]
        self.visit(node.value)
        self.visit(node.slice)


def collect_string_annotation_names(tree: ast.AST) -> set[str]:
    """Collect names used in string annotations (forward references)."""
    visitor = StringAnnotationVisitor()
    visitor.visit(tree)
    return visitor.used_names


def collect_dunder_all_names(tree: ast.AST) -> set[str]:
    """Collect names exported via __all__.

    Names in __all__ are considered "used" because they're part of the public API.
    """
    names: set[str] = set()

    for node in ast.walk(tree):
        # Look for __all__ = [...] or __all__ += [...]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    names.update(_extract_string_list(node.value))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                names.update(_extract_string_list(node.value))

    return names


def _extract_string_list(node: ast.expr) -> set[str]:
    """Extract string values from a list/tuple literal."""
    names: set[str] = set()

    if isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.add(elt.value)

    return names
