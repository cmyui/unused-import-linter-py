from __future__ import annotations

import ast
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from enum import auto

from remove_unused_imports._data import ImportInfo

# =============================================================================
# Scope Analysis Infrastructure
# =============================================================================


class ScopeType(Enum):
    """Types of scopes in Python."""

    MODULE = auto()  # Top-level module scope
    FUNCTION = auto()  # Function/method/lambda scope
    CLASS = auto()  # Class body (special: doesn't enclose nested functions)
    COMPREHENSION = auto()  # List/dict/set/generator comprehension


@dataclass
class Scope:
    """Represents a single scope in the scope chain."""

    scope_type: ScopeType
    bindings: set[str] = field(default_factory=set)  # Names bound in this scope
    name: str = ""  # For debugging (function name, class name, etc.)


class ScopeStack:
    """Manages the scope chain during AST traversal."""

    def __init__(self) -> None:
        # Initialize with module scope
        self.scopes: list[Scope] = [Scope(ScopeType.MODULE, name="<module>")]

    def push(self, scope: Scope) -> None:
        """Push a new scope onto the stack."""
        self.scopes.append(scope)

    def pop(self) -> Scope:
        """Pop the current scope from the stack."""
        return self.scopes.pop()

    def current(self) -> Scope:
        """Get the current (innermost) scope."""
        return self.scopes[-1]

    def add_binding(self, name: str) -> None:
        """Add a name binding to the current scope."""
        self.current().bindings.add(name)

    def resolves_to_module_scope(self, name: str) -> bool:
        """Check if a name lookup would resolve to module scope.

        Follows Python's LEGB (Local, Enclosing, Global, Builtin) rule,
        with special handling for class scope.
        """
        # Walk from innermost to outermost scope
        for i in range(len(self.scopes) - 1, -1, -1):
            scope = self.scopes[i]

            # Class scope is special: when looking up from inside a method
            # (nested function), class-level bindings are NOT visible.
            # They're only visible directly in the class body itself.
            if scope.scope_type == ScopeType.CLASS:
                # If we're directly in the class body (class is current scope),
                # class bindings ARE visible (check below).
                # If we're in a nested scope (method/function inside class),
                # skip the class scope entirely.
                if i < len(self.scopes) - 1:
                    continue

            if name in scope.bindings:
                # Found the binding - is it module scope?
                return scope.scope_type == ScopeType.MODULE

        # Not found in any scope - would be a global/builtin or undefined.
        # For our purposes, if not found locally, assume it resolves to module scope.
        return True


class ScopeAwareNameCollector(ast.NodeVisitor):
    """Collect names used at module scope, with full scope analysis.

    Unlike NameUsageCollector, this class tracks name bindings at each scope
    level and only reports names that actually resolve to module scope.
    """

    def __init__(self) -> None:
        self.module_scope_usages: set[str] = set()
        self._scope_stack = ScopeStack()
        # Track names declared global/nonlocal
        self._global_names: set[str] = set()
        self._nonlocal_names: set[str] = set()
        # Track names bound at module level by non-import statements
        # These shadow any imports of the same name
        self._module_level_shadows: set[str] = set()

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _add_binding_from_target(self, target: ast.expr) -> None:
        """Extract and add bindings from assignment targets."""
        if isinstance(target, ast.Name):
            self._scope_stack.add_binding(target.id)
            # Track module-level shadows
            if self._scope_stack.current().scope_type == ScopeType.MODULE:
                self._module_level_shadows.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._add_binding_from_target(elt)
        elif isinstance(target, ast.Starred):
            self._add_binding_from_target(target.value)
        # ast.Attribute and ast.Subscript don't create new bindings

    def _bind_function_parameters(self, args: ast.arguments) -> None:
        """Bind all function parameters in the current scope."""
        for arg in args.args:
            self._scope_stack.add_binding(arg.arg)
        for arg in args.posonlyargs:
            self._scope_stack.add_binding(arg.arg)
        for arg in args.kwonlyargs:
            self._scope_stack.add_binding(arg.arg)
        if args.vararg:
            self._scope_stack.add_binding(args.vararg.arg)
        if args.kwarg:
            self._scope_stack.add_binding(args.kwarg.arg)

    def _visit_function_annotations_and_defaults(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """Visit annotations and defaults in the CURRENT scope (not function body)."""
        # Annotations and defaults are evaluated at function definition time
        if node.returns:
            self.visit(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation:
                self.visit(arg.annotation)
        if node.args.vararg and node.args.vararg.annotation:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            self.visit(node.args.kwarg.annotation)
        for default in node.args.defaults:
            self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default is not None:
                self.visit(kw_default)

    # -------------------------------------------------------------------------
    # Skip import statements (they don't count as usage)
    # -------------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        # Don't count import statements as usage, and don't add bindings.
        # We want to detect shadowing by non-import bindings (parameters,
        # assignments, etc.), not by other imports.
        pass

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Don't count import statements as usage, and don't add bindings.
        pass

    # -------------------------------------------------------------------------
    # Name usage tracking (Load contexts)
    # -------------------------------------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        """Track name usages, resolving to scope."""
        # Only Load context counts as usage
        # Store context is handled by visit_Assign, visit_For, etc.
        if isinstance(node.ctx, ast.Load):
            # Check if this name resolves to module scope
            if self._scope_stack.resolves_to_module_scope(node.id):
                # Don't count as import usage if shadowed at module level
                if node.id not in self._module_level_shadows:
                    self.module_scope_usages.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Track attribute access root names."""
        # Walk up to find the root name
        # For both Load (obj.attr) and Store (obj.attr = x), we use the root object
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
            if self._scope_stack.resolves_to_module_scope(current.id):
                # Don't count as import usage if shadowed at module level
                if current.id not in self._module_level_shadows:
                    self.module_scope_usages.add(current.id)
        self.generic_visit(node)

    # -------------------------------------------------------------------------
    # Function scope
    # -------------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Handle function definitions."""
        # 1. Visit decorators in CURRENT scope FIRST
        # Decorators are evaluated before the function name is bound,
        # so @foo must resolve before `def foo` creates a binding.
        for decorator in node.decorator_list:
            self.visit(decorator)

        # 2. Bind function name in CURRENT scope
        self._add_binding_with_shadow_tracking(node.name)

        # 3. Visit annotations and defaults in CURRENT scope
        self._visit_function_annotations_and_defaults(node)

        # 4. Create new scope for function body
        self._scope_stack.push(Scope(ScopeType.FUNCTION, name=node.name))

        # 5. Bind parameters in the new function scope
        self._bind_function_parameters(node.args)

        # 6. Visit function body
        for child in node.body:
            self.visit(child)

        # 7. Pop function scope
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Handle async function definitions (same as sync)."""
        # Visit decorators FIRST, before binding function name
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._add_binding_with_shadow_tracking(node.name)
        self._visit_function_annotations_and_defaults(node)
        self._scope_stack.push(Scope(ScopeType.FUNCTION, name=node.name))
        self._bind_function_parameters(node.args)
        for child in node.body:
            self.visit(child)
        self._scope_stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Handle lambda expressions."""
        # Lambdas don't bind a name, just create a scope
        self._scope_stack.push(Scope(ScopeType.FUNCTION, name="<lambda>"))
        self._bind_function_parameters(node.args)
        self.visit(node.body)
        self._scope_stack.pop()

    # -------------------------------------------------------------------------
    # Class scope
    # -------------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Handle class definitions."""
        # 1. Visit decorators in CURRENT scope FIRST
        # Decorators are evaluated before the class name is bound.
        for decorator in node.decorator_list:
            self.visit(decorator)

        # 2. Bind class name in CURRENT scope
        self._add_binding_with_shadow_tracking(node.name)

        # 3. Visit base classes and keywords in CURRENT scope
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)

        # 4. Create new CLASS scope for body
        self._scope_stack.push(Scope(ScopeType.CLASS, name=node.name))

        # 5. Visit class body
        for child in node.body:
            self.visit(child)

        # 6. Pop class scope
        self._scope_stack.pop()

    # -------------------------------------------------------------------------
    # Assignment bindings
    # -------------------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        """Regular assignments bind targets."""
        # Visit value first (RHS is evaluated before binding)
        self.visit(node.value)
        # Then bind targets (but also track usage for attribute/subscript targets)
        for target in node.targets:
            self._add_binding_from_target(target)
            # For attribute and subscript assignments, the root object is used
            if isinstance(target, (ast.Attribute, ast.Subscript)):
                self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Annotated assignments."""
        self.visit(node.annotation)
        if node.value:
            self.visit(node.value)
        self._add_binding_from_target(node.target)
        # For attribute and subscript assignments, the root object is used
        if isinstance(node.target, (ast.Attribute, ast.Subscript)):
            self.visit(node.target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Augmented assignments (+=, etc.) don't create new bindings.

        For `x += 1`, the name `x` must already exist, and this is both
        a read and a write. We need to track the read as a usage.
        """
        # The target is read (to get current value) - track as usage
        if isinstance(node.target, ast.Name):
            if self._scope_stack.resolves_to_module_scope(node.target.id):
                if node.target.id not in self._module_level_shadows:
                    self.module_scope_usages.add(node.target.id)
        elif isinstance(node.target, ast.Attribute):
            # For attribute augmented assign like obj.x += 1, obj is used
            current: ast.expr = node.target
            while isinstance(current, ast.Attribute):
                current = current.value
            if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
                if self._scope_stack.resolves_to_module_scope(current.id):
                    if current.id not in self._module_level_shadows:
                        self.module_scope_usages.add(current.id)
        # Visit the value expression
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        """Walrus operator (:=) - binds in enclosing non-comprehension scope."""
        self.visit(node.value)
        # Find enclosing non-comprehension scope to add binding
        for i in range(len(self._scope_stack.scopes) - 1, -1, -1):
            scope = self._scope_stack.scopes[i]
            if scope.scope_type != ScopeType.COMPREHENSION:
                scope.bindings.add(node.target.id)
                break

    # -------------------------------------------------------------------------
    # Loop and exception bindings
    # -------------------------------------------------------------------------

    def visit_For(self, node: ast.For) -> None:
        """For loops bind the target variable."""
        self.visit(node.iter)
        self._add_binding_from_target(node.target)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        """Async for loops."""
        self.visit(node.iter)
        self._add_binding_from_target(node.target)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_With(self, node: ast.With) -> None:
        """With statements bind 'as' targets."""
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self._add_binding_from_target(item.optional_vars)
        for child in node.body:
            self.visit(child)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        """Async with statements."""
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self._add_binding_from_target(item.optional_vars)
        for child in node.body:
            self.visit(child)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Exception handlers bind the 'as' variable."""
        if node.type:
            self.visit(node.type)
        if node.name:
            self._add_binding_with_shadow_tracking(node.name)
        for child in node.body:
            self.visit(child)

    def visit_Match(self, node: ast.Match) -> None:
        """Match statements (Python 3.10+)."""
        self.visit(node.subject)
        for case in node.cases:
            self.visit(case)

    def visit_match_case(self, node: ast.match_case) -> None:
        """Match case clauses bind pattern variables."""
        self._bind_match_pattern(node.pattern)
        if node.guard:
            self.visit(node.guard)
        for child in node.body:
            self.visit(child)

    def _add_binding_with_shadow_tracking(self, name: str) -> None:
        """Add a binding and track if it shadows an import at module level."""
        self._scope_stack.add_binding(name)
        if self._scope_stack.current().scope_type == ScopeType.MODULE:
            self._module_level_shadows.add(name)

    def _bind_match_pattern(self, pattern: ast.pattern) -> None:
        """Extract bindings from match patterns."""
        if isinstance(pattern, ast.MatchAs):
            if pattern.name:
                self._add_binding_with_shadow_tracking(pattern.name)
            if pattern.pattern:
                self._bind_match_pattern(pattern.pattern)
        elif isinstance(pattern, ast.MatchStar):
            if pattern.name:
                self._add_binding_with_shadow_tracking(pattern.name)
        elif isinstance(pattern, ast.MatchMapping):
            for p in pattern.patterns:
                self._bind_match_pattern(p)
            if pattern.rest:
                self._add_binding_with_shadow_tracking(pattern.rest)
        elif isinstance(pattern, ast.MatchSequence):
            for p in pattern.patterns:
                self._bind_match_pattern(p)
        elif isinstance(pattern, ast.MatchClass):
            for p in pattern.patterns:
                self._bind_match_pattern(p)
            for p in pattern.kwd_patterns:
                self._bind_match_pattern(p)
        elif isinstance(pattern, ast.MatchOr):
            for p in pattern.patterns:
                self._bind_match_pattern(p)
        # MatchValue and MatchSingleton don't bind names

    # -------------------------------------------------------------------------
    # Comprehension scope
    # -------------------------------------------------------------------------

    def _visit_comprehension(
        self,
        generators: list[ast.comprehension],
        *exprs: ast.expr | None,
    ) -> None:
        """Handle comprehension scope correctly.

        The first iterator is evaluated in the enclosing scope, but all other
        parts (targets, filters, subsequent iterators) are in comprehension scope.
        """
        # First iterator is evaluated in enclosing scope
        self.visit(generators[0].iter)

        # Create comprehension scope
        self._scope_stack.push(Scope(ScopeType.COMPREHENSION, name="<comprehension>"))

        # Bind first target in comprehension scope
        self._add_binding_from_target(generators[0].target)
        for if_ in generators[0].ifs:
            self.visit(if_)

        # Handle remaining generators
        for gen in generators[1:]:
            self.visit(gen.iter)
            self._add_binding_from_target(gen.target)
            for if_ in gen.ifs:
                self.visit(if_)

        # Visit result expressions
        for expr in exprs:
            if expr is not None:
                self.visit(expr)

        self._scope_stack.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        """List comprehensions have their own scope."""
        self._visit_comprehension(node.generators, node.elt)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        """Set comprehensions have their own scope."""
        self._visit_comprehension(node.generators, node.elt)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Dict comprehensions have their own scope."""
        self._visit_comprehension(node.generators, node.key, node.value)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        """Generator expressions have their own scope."""
        self._visit_comprehension(node.generators, node.elt)

    # -------------------------------------------------------------------------
    # Global/Nonlocal declarations
    # -------------------------------------------------------------------------

    def visit_Global(self, node: ast.Global) -> None:
        """Global declarations make names resolve to module scope."""
        # These names should NOT be added as local bindings
        # They're already at module scope
        pass

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        """Nonlocal declarations make names resolve to enclosing scope."""
        # These names should NOT be added as local bindings
        # They refer to an enclosing scope
        pass


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

            # Use alias's lineno for multi-line imports (Python 3.10+)
            # This ensures noqa comments on specific lines are respected
            alias_lineno = getattr(alias, "lineno", node.lineno)
            self.imports.append(
                ImportInfo(
                    name=name,
                    module="",
                    original_name=alias.name,
                    lineno=alias_lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or 0,
                    is_from_import=False,
                    full_node_lineno=node.lineno,
                    full_node_end_lineno=node.end_lineno or node.lineno,
                    level=0,  # Regular imports are always absolute
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
            # Use alias's lineno for multi-line imports (Python 3.10+)
            # This ensures noqa comments on specific lines are respected
            alias_lineno = getattr(alias, "lineno", node.lineno)
            self.imports.append(
                ImportInfo(
                    name=name,
                    module=module,
                    original_name=alias.name,
                    lineno=alias_lineno,
                    col_offset=node.col_offset,
                    end_lineno=node.end_lineno or node.lineno,
                    end_col_offset=node.end_col_offset or 0,
                    is_from_import=True,
                    full_node_lineno=node.lineno,
                    full_node_end_lineno=node.end_lineno or node.lineno,
                    level=node.level,  # Number of dots for relative imports
                ),
            )
        self.generic_visit(node)

    # Alias for the actual AST node name
    visit_ImportFrom = visit_FromImport


class NameUsageCollector(ast.NodeVisitor):
    """Collect all name usages from expression ASTs.

    This is a simple collector used only for parsing string annotations.
    When parsing with mode="eval", we only get expression nodes, so this
    collector only needs to handle expression-related visitors.
    """

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        # Only count Load contexts as usages
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # For attribute access like 'typing.Optional', we need to track 'typing'
        # Walk up to find the root name
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
            self.used_names.add(current.id)
        self.generic_visit(node)


class StringAnnotationVisitor(ast.NodeVisitor):
    """Extract names from string annotations (forward references).

    Parses strings that appear in annotation contexts:
    - Function parameter annotations
    - Function return annotations
    - Variable annotations (AnnAssign)
    - Strings inside type subscripts (e.g., Optional["Foo"])
    """

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def _parse_string_annotation(self, node: ast.expr | None) -> None:
        """Parse a potential string annotation and extract names."""
        if node is None:
            return
        # Handle direct string constant
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode="eval")
                collector = NameUsageCollector()
                collector.visit(parsed)
                self.used_names.update(collector.used_names)
            except SyntaxError:
                pass
        # Handle subscripts like Optional["Foo"] - recurse into the slice
        elif isinstance(node, ast.Subscript):
            self._parse_string_annotation(node.slice)
            # Also check the value (e.g., for nested like Dict[str, "Foo"])
            self._parse_string_annotation(node.value)
        # Handle tuples in subscripts like Dict["Key", "Value"]
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                self._parse_string_annotation(elt)
        # Handle BinOp for union types like "Foo" | "Bar"
        elif isinstance(node, ast.BinOp):
            self._parse_string_annotation(node.left)
            self._parse_string_annotation(node.right)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Check return annotation
        self._parse_string_annotation(node.returns)
        # Check parameter annotations
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            self._parse_string_annotation(arg.annotation)
        if node.args.vararg:
            self._parse_string_annotation(node.args.vararg.annotation)
        if node.args.kwarg:
            self._parse_string_annotation(node.args.kwarg.annotation)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Same as FunctionDef
        self._parse_string_annotation(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            self._parse_string_annotation(arg.annotation)
        if node.args.vararg:
            self._parse_string_annotation(node.args.vararg.annotation)
        if node.args.kwarg:
            self._parse_string_annotation(node.args.kwarg.annotation)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Variable annotation like `x: "Foo" = ...`
        self._parse_string_annotation(node.annotation)
        self.generic_visit(node)


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
