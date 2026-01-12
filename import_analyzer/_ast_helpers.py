from __future__ import annotations

import ast
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from enum import auto

from import_analyzer._data import ImportInfo

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


@dataclass
class AttributeUsage:
    """A module.attr1.attr2... usage location."""

    attr_path: list[str]  # Path of attributes (e.g., ["mod", "LOGGER"] for pkg.mod.LOGGER)
    lineno: int  # Line number of the usage
    col_offset: int  # Column offset of the start of the root module name


class AttributeAccessCollector(ast.NodeVisitor):
    """Collect module.attr usages for 'import module' statements.

    Given source like:
        import pkg
        pkg.mod.LOGGER.info("hello")
        pkg.Config.DEBUG

    This collector produces:
        {
            "pkg": [
                AttributeUsage(["mod", "LOGGER"], 2, 0),
                AttributeUsage(["Config"], 3, 0),
            ]
        }

    Handles:
    - Aliased imports: 'import models as m' + 'm.LOGGER'
    - Nested access: 'import pkg' + 'pkg.mod.LOGGER'
    - Any depth of nesting
    """

    def __init__(self, module_imports: set[str]) -> None:
        """Initialize the collector.

        Args:
            module_imports: Set of names bound by 'import X' or 'import X as Y'
                           (the bound name, which is Y if aliased, X otherwise)
        """
        self.module_imports = module_imports
        self.usages: dict[str, list[AttributeUsage]] = {}
        for name in module_imports:
            self.usages[name] = []
        # Track which attribute chains we've already recorded (to avoid duplicates)
        # Key: (root_name, lineno, col_offset, tuple(attr_path))
        self._seen: set[tuple[str, int, int, tuple[str, ...]]] = set()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Track attribute access chains on imported modules."""
        # Only interested in Load context (reading, not assignment to attribute)
        if not isinstance(node.ctx, ast.Load):
            self.generic_visit(node)
            return

        # Walk up to find the root Name and collect the attribute path
        attr_path: list[str] = []
        current: ast.expr = node

        while isinstance(current, ast.Attribute):
            attr_path.append(current.attr)
            current = current.value

        # Check if the root is a Name node
        if not isinstance(current, ast.Name):
            self.generic_visit(node)
            return

        root_name = current.id

        # Check if this name refers to an imported module
        if root_name not in self.module_imports:
            self.generic_visit(node)
            return

        # Reverse to get path from root to leaf
        attr_path.reverse()

        # Check if we've already recorded this exact chain
        # (nested visits can produce duplicates e.g., pkg.mod.LOGGER visits both
        # the full chain and the pkg.mod part)
        key = (root_name, current.lineno, current.col_offset, tuple(attr_path))
        if key in self._seen:
            self.generic_visit(node)
            return
        self._seen.add(key)

        # Record this usage
        self.usages[root_name].append(
            AttributeUsage(
                attr_path=attr_path,
                lineno=current.lineno,
                col_offset=current.col_offset,
            ),
        )

        self.generic_visit(node)


def _is_typing_name(node: ast.expr, name: str) -> bool:
    """Check if node refers to a typing construct by name.

    Handles:
    - Direct name: Literal, Annotated
    - Attribute access: typing.Literal, typing_extensions.Annotated
    """
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    return False


class StringAnnotationVisitor(ast.NodeVisitor):
    """Extract names from string annotations (forward references).

    Parses strings that appear in annotation contexts:
    - Function parameter annotations
    - Function return annotations
    - Variable annotations (AnnAssign)
    - Strings inside type subscripts (e.g., Optional["Foo"])
    - TypeAlias RHS (when annotation is TypeAlias)
    - typing.cast() first argument
    - TypeVar() constraints and bound keyword

    Special handling:
    - Literal[] contents are NOT parsed (they're literal values, not types)
    - Annotated[] only first arg is parsed (rest is metadata)
    """

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def _parse_string_as_type(self, value: str) -> None:
        """Parse a string value as a type annotation."""
        try:
            parsed = ast.parse(value, mode="eval")
            collector = NameUsageCollector()
            collector.visit(parsed)
            self.used_names.update(collector.used_names)
        except SyntaxError:
            pass

    def _parse_string_annotation(self, node: ast.expr | None) -> None:
        """Parse a potential string annotation and extract names."""
        if node is None:
            return
        # Handle direct string constant
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            self._parse_string_as_type(node.value)
        # Handle subscripts like Optional["Foo"] - recurse into the slice
        elif isinstance(node, ast.Subscript):
            # Special case: Literal[] contents are NOT type annotations
            if _is_typing_name(node.value, "Literal"):
                # Don't parse slice - Literal contents are literal values
                # But DO recurse into the value itself (in case it's nested)
                self._parse_string_annotation(node.value)
                return

            # Special case: Annotated[] - only first arg is type annotation
            if _is_typing_name(node.value, "Annotated"):
                # Only process first element of slice
                if isinstance(node.slice, ast.Tuple) and node.slice.elts:
                    self._parse_string_annotation(node.slice.elts[0])
                else:
                    # Single arg Annotated (unusual but valid)
                    self._parse_string_annotation(node.slice)
                # Process the value too (Annotated itself)
                self._parse_string_annotation(node.value)
                return

            # Normal case: recurse into slice and value
            self._parse_string_annotation(node.slice)
            self._parse_string_annotation(node.value)
        # Handle tuples in subscripts like Dict["Key", "Value"]
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                self._parse_string_annotation(elt)
        # Handle lists in subscripts like Callable[["Arg1", "Arg2"], "Return"]
        elif isinstance(node, ast.List):
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

        # Special case: TypeAlias - RHS is also annotation context
        # e.g., PathAlias: TypeAlias = "Path"
        if _is_typing_name(node.annotation, "TypeAlias") and node.value:
            self._parse_string_annotation(node.value)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Handle special typing functions like cast() and TypeVar()."""
        # typing.cast(type, value) - first arg is annotation context
        if _is_typing_name(node.func, "cast") and node.args:
            self._parse_string_annotation(node.args[0])

        # TypeVar("T", constraint1, constraint2, ..., bound=type)
        # - Args after first are constraints (annotation context)
        # - bound keyword is annotation context
        if _is_typing_name(node.func, "TypeVar"):
            # Process constraint args (skip first which is the name)
            for arg in node.args[1:]:
                self._parse_string_annotation(arg)
            # Process bound keyword
            for kw in node.keywords:
                if kw.arg == "bound":
                    self._parse_string_annotation(kw.value)

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Handle type subscripts like Callable[["Arg"], "Return"].

        This handles forward references in type expressions that appear
        outside of annotation contexts (e.g., type aliases).
        """
        # Skip Literal contents - not type annotations
        if _is_typing_name(node.value, "Literal"):
            self.generic_visit(node)
            return

        # For Annotated, only first arg is annotation
        if _is_typing_name(node.value, "Annotated"):
            if isinstance(node.slice, ast.Tuple) and node.slice.elts:
                self._parse_string_annotation(node.slice.elts[0])
            else:
                self._parse_string_annotation(node.slice)
            self.generic_visit(node)
            return

        # For other type subscripts, parse all string elements as annotations
        self._parse_string_annotation(node.slice)
        self.generic_visit(node)


def collect_string_annotation_names(tree: ast.AST) -> set[str]:
    """Collect names used in string annotations (forward references)."""
    visitor = StringAnnotationVisitor()
    visitor.visit(tree)
    return visitor.used_names


class TypeCommentVisitor(ast.NodeVisitor):
    """Extract names from type comments (PEP 484 style).

    Parses type comments on:
    - Function definitions (signature format: (int, str) -> bool)
    - Function arguments (per-arg format)
    - Assignments (variable type comments)
    - For loops
    - With statements

    Type comments are only processed if no PEP 526 annotation exists
    on the same construct (PEP 526 takes precedence).
    """

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def _parse_type_string(self, type_str: str) -> None:
        """Parse a type expression string and extract names."""
        try:
            parsed = ast.parse(type_str, mode="eval")
            collector = NameUsageCollector()
            collector.visit(parsed)
            self.used_names.update(collector.used_names)
        except SyntaxError:
            pass

    def _split_type_args(self, args_str: str) -> list[str]:
        """Split comma-separated type args, respecting brackets."""
        result: list[str] = []
        current: list[str] = []
        depth = 0
        for char in args_str:
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            elif char == "," and depth == 0:
                result.append("".join(current))
                current = []
                continue
            current.append(char)
        if current:
            result.append("".join(current))
        return result

    def _parse_func_type_comment(self, type_comment: str) -> None:
        """Parse function signature type comment: (int, str) -> bool"""
        # Skip "type: ignore" directives (not a type annotation)
        stripped = type_comment.strip()
        if stripped.startswith("ignore"):
            return

        # Split on " -> " to separate args from return type
        if " -> " in type_comment:
            args_part, return_part = type_comment.rsplit(" -> ", 1)
            self._parse_type_string(return_part.strip())

            # Parse args: "(int, str)" or "(...)"
            args_part = args_part.strip()
            if args_part.startswith("(") and args_part.endswith(")"):
                args_inner = args_part[1:-1].strip()
                if args_inner != "...":
                    for arg_type in self._split_type_args(args_inner):
                        arg_type = arg_type.strip()
                        # Handle *args and **kwargs: (*str, **int)
                        if arg_type.startswith("**"):
                            arg_type = arg_type[2:]
                        elif arg_type.startswith("*"):
                            arg_type = arg_type[1:]
                        if arg_type:
                            self._parse_type_string(arg_type)
        else:
            # No return type arrow, parse the whole thing as a type
            self._parse_type_string(type_comment)

    def _has_annotations(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        """Check if function has any PEP 526 style annotations."""
        if node.returns:
            return True
        all_args = (
            node.args.args
            + node.args.posonlyargs
            + node.args.kwonlyargs
        )
        for arg in all_args:
            if arg.annotation:
                return True
        if node.args.vararg and node.args.vararg.annotation:
            return True
        if node.args.kwarg and node.args.kwarg.annotation:
            return True
        return False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Only process function type_comment if no PEP 526 annotations exist
        if node.type_comment and not self._has_annotations(node):
            self._parse_func_type_comment(node.type_comment)

        # Check per-argument type comments (only if arg has no annotation)
        all_args = (
            node.args.args
            + node.args.posonlyargs
            + node.args.kwonlyargs
        )
        for arg in all_args:
            if arg.type_comment and not arg.annotation:
                self._parse_type_string(arg.type_comment)
        if node.args.vararg:
            if node.args.vararg.type_comment and not node.args.vararg.annotation:
                self._parse_type_string(node.args.vararg.type_comment)
        if node.args.kwarg:
            if node.args.kwarg.type_comment and not node.args.kwarg.annotation:
                self._parse_type_string(node.args.kwarg.type_comment)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Same logic as FunctionDef
        if node.type_comment and not self._has_annotations(node):
            self._parse_func_type_comment(node.type_comment)

        all_args = (
            node.args.args
            + node.args.posonlyargs
            + node.args.kwonlyargs
        )
        for arg in all_args:
            if arg.type_comment and not arg.annotation:
                self._parse_type_string(arg.type_comment)
        if node.args.vararg:
            if node.args.vararg.type_comment and not node.args.vararg.annotation:
                self._parse_type_string(node.args.vararg.type_comment)
        if node.args.kwarg:
            if node.args.kwarg.type_comment and not node.args.kwarg.annotation:
                self._parse_type_string(node.args.kwarg.type_comment)

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Assign nodes can have type_comment but never have annotations
        # (AnnAssign is used for annotated assignments like x: int = 1)
        if node.type_comment:
            self._parse_type_string(node.type_comment)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if node.type_comment:
            self._parse_type_string(node.type_comment)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        if node.type_comment:
            self._parse_type_string(node.type_comment)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        if node.type_comment:
            self._parse_type_string(node.type_comment)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        if node.type_comment:
            self._parse_type_string(node.type_comment)
        self.generic_visit(node)


def collect_type_comment_names(tree: ast.AST) -> set[str]:
    """Collect names used in type comments (PEP 484 style)."""
    visitor = TypeCommentVisitor()
    visitor.visit(tree)
    return visitor.used_names


@dataclass
class TypeStringAttrUsage:
    """Internal: attribute access found in a type string before mapping to source."""

    root_name: str  # "models" in "models.LOGGER"
    attr_path: list[str]  # ["LOGGER"]
    lineno: int  # Line number in source
    col_offset: int  # Column where the attribute access starts
    end_col_offset: int  # Column where it ends
    context: str  # "type_comment" or "string_annotation"


class TypeStringAttributeCollector(ast.NodeVisitor):
    """Collect module.attr usages in type comments and string annotations.

    Given source like:
        import models
        x = None  # type: models.User
        y: "models.Config" = None

    This collector produces usages for:
        - models.User from the type comment
        - models.Config from the string annotation

    Handles:
    - Type comments: x = None  # type: models.User
    - String annotations: x: "models.User" = None
    - Nested generics: # type: Dict[str, models.User]
    - Multiple attrs in same type: # type: Tuple[models.User, models.Config]
    - Aliased imports: import models as m; # type: m.User
    """

    def __init__(self, module_imports: set[str]) -> None:
        """Initialize the collector.

        Args:
            module_imports: Set of names bound by 'import X' or 'import X as Y'
        """
        self.module_imports = module_imports
        self.usages: list[TypeStringAttrUsage] = []

    def _extract_attrs_from_expr(
        self,
        expr: ast.expr,
        type_str: str,
        lineno: int,
        base_col: int,
        context: str,
    ) -> None:
        """Extract attribute accesses from a parsed expression."""
        for node in ast.walk(expr):
            if not isinstance(node, ast.Attribute):
                continue

            # Walk up to find the root Name and collect the attribute path
            attr_path: list[str] = []
            current: ast.expr = node

            while isinstance(current, ast.Attribute):
                attr_path.append(current.attr)
                current = current.value

            # Check if the root is a Name node
            if not isinstance(current, ast.Name):
                continue

            root_name = current.id

            # Check if this name refers to an imported module
            if root_name not in self.module_imports:
                continue

            # Reverse to get path from root to leaf
            attr_path.reverse()

            # Build the full attribute string to find in the type string
            full_attr = f"{root_name}.{'.'.join(attr_path)}"

            # Find position in the type string
            # Note: There could be multiple occurrences, handle each
            start = 0
            while True:
                pos = type_str.find(full_attr, start)
                if pos == -1:
                    break

                # Calculate absolute column positions
                col_offset = base_col + pos
                end_col_offset = col_offset + len(full_attr)

                self.usages.append(
                    TypeStringAttrUsage(
                        root_name=root_name,
                        attr_path=attr_path,
                        lineno=lineno,
                        col_offset=col_offset,
                        end_col_offset=end_col_offset,
                        context=context,
                    ),
                )

                # Move past this occurrence
                start = pos + len(full_attr)
                break  # Only record once per AST node

    def _process_type_string(
        self,
        type_str: str,
        lineno: int,
        col_offset: int,
        context: str,
    ) -> None:
        """Parse a type string and extract attribute accesses."""
        try:
            parsed = ast.parse(type_str, mode="eval")
            self._extract_attrs_from_expr(
                parsed.body, type_str, lineno, col_offset, context,
            )
        except SyntaxError:
            pass

    def _process_func_type_comment(
        self,
        type_comment: str,
        lineno: int,
        col_offset: int,
    ) -> None:
        """Process function signature type comment: (int, str) -> bool"""
        stripped = type_comment.strip()
        if stripped.startswith("ignore"):
            return

        # For function type comments, we need to find where the comment starts
        # in the source. The type_comment attribute doesn't include "# type:"
        if " -> " in type_comment:
            args_part, return_part = type_comment.rsplit(" -> ", 1)

            # Process return type
            return_start = type_comment.rfind(return_part)
            self._process_type_string(
                return_part.strip(),
                lineno,
                col_offset + return_start,
                "type_comment",
            )

            # Process args: "(int, str)" or "(...)"
            args_part = args_part.strip()
            if args_part.startswith("(") and args_part.endswith(")"):
                args_inner = args_part[1:-1].strip()
                if args_inner != "...":
                    # Process each arg individually
                    current_pos = type_comment.find("(") + 1
                    for arg_type in self._split_type_args(args_inner):
                        arg_type_stripped = arg_type.strip()
                        # Handle *args and **kwargs
                        if arg_type_stripped.startswith("**"):
                            arg_type_stripped = arg_type_stripped[2:]
                        elif arg_type_stripped.startswith("*"):
                            arg_type_stripped = arg_type_stripped[1:]
                        if arg_type_stripped:
                            # Find where this arg starts in the original string
                            arg_pos = type_comment.find(arg_type.strip(), current_pos)
                            self._process_type_string(
                                arg_type_stripped,
                                lineno,
                                col_offset + arg_pos,
                                "type_comment",
                            )
                        current_pos += len(arg_type) + 1  # +1 for comma
        else:
            self._process_type_string(type_comment, lineno, col_offset, "type_comment")

    def _split_type_args(self, args_str: str) -> list[str]:
        """Split comma-separated type args, respecting brackets."""
        result: list[str] = []
        current: list[str] = []
        depth = 0
        for char in args_str:
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            elif char == "," and depth == 0:
                result.append("".join(current))
                current = []
                continue
            current.append(char)
        if current:
            result.append("".join(current))
        return result

    def _has_annotations(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        """Check if function has any PEP 526 style annotations."""
        if node.returns:
            return True
        all_args = (
            node.args.args + node.args.posonlyargs + node.args.kwonlyargs
        )
        for arg in all_args:
            if arg.annotation:
                return True
        if node.args.vararg and node.args.vararg.annotation:
            return True
        if node.args.kwarg and node.args.kwarg.annotation:
            return True
        return False

    def _process_string_annotation(
        self,
        node: ast.expr | None,
        lineno: int | None = None,
    ) -> None:
        """Process a potential string annotation node."""
        if node is None:
            return

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # The col_offset of the string literal (after the quote)
            # For a string annotation like x: "models.User", the string
            # starts after the opening quote
            self._process_type_string(
                node.value,
                node.lineno,
                node.col_offset + 1,  # +1 to skip the opening quote
                "string_annotation",
            )
        elif isinstance(node, ast.Subscript):
            self._process_string_annotation(node.slice, lineno)
            self._process_string_annotation(node.value, lineno)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                self._process_string_annotation(elt, lineno)
        elif isinstance(node, ast.BinOp):
            self._process_string_annotation(node.left, lineno)
            self._process_string_annotation(node.right, lineno)

    def _get_func_type_comment_lineno(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> int:
        """Determine the actual line number of a function type comment.

        For inline type comments (same line as def), returns node.lineno.
        For body-type comments (first line of body), returns node.body[0].lineno - 1.
        """
        # If function has a body and body starts after the def line
        if node.body and node.body[0].lineno > node.lineno:
            # Body-type comment is on the line before the first statement
            # but after the def line
            return node.body[0].lineno - 1
        # Inline type comment
        return node.lineno

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Process function type_comment if no PEP 526 annotations
        if node.type_comment and not self._has_annotations(node):
            # Determine actual line of the type comment
            type_comment_lineno = self._get_func_type_comment_lineno(node)
            self._process_func_type_comment(
                node.type_comment, type_comment_lineno, 0,
            )

        # Process per-argument type comments
        all_args = node.args.args + node.args.posonlyargs + node.args.kwonlyargs
        for arg in all_args:
            if arg.type_comment and not arg.annotation:
                self._process_type_string(
                    arg.type_comment, arg.lineno, 0, "type_comment",
                )
        if node.args.vararg and node.args.vararg.type_comment:
            if not node.args.vararg.annotation:
                self._process_type_string(
                    node.args.vararg.type_comment,
                    node.args.vararg.lineno,
                    0,
                    "type_comment",
                )
        if node.args.kwarg and node.args.kwarg.type_comment:
            if not node.args.kwarg.annotation:
                self._process_type_string(
                    node.args.kwarg.type_comment,
                    node.args.kwarg.lineno,
                    0,
                    "type_comment",
                )

        # Process string annotations
        self._process_string_annotation(node.returns)
        for arg in all_args:
            self._process_string_annotation(arg.annotation)
        if node.args.vararg:
            self._process_string_annotation(node.args.vararg.annotation)
        if node.args.kwarg:
            self._process_string_annotation(node.args.kwarg.annotation)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Same as FunctionDef
        if node.type_comment and not self._has_annotations(node):
            type_comment_lineno = self._get_func_type_comment_lineno(node)
            self._process_func_type_comment(
                node.type_comment, type_comment_lineno, 0,
            )

        all_args = node.args.args + node.args.posonlyargs + node.args.kwonlyargs
        for arg in all_args:
            if arg.type_comment and not arg.annotation:
                self._process_type_string(
                    arg.type_comment, arg.lineno, 0, "type_comment",
                )
        if node.args.vararg and node.args.vararg.type_comment:
            if not node.args.vararg.annotation:
                self._process_type_string(
                    node.args.vararg.type_comment,
                    node.args.vararg.lineno,
                    0,
                    "type_comment",
                )
        if node.args.kwarg and node.args.kwarg.type_comment:
            if not node.args.kwarg.annotation:
                self._process_type_string(
                    node.args.kwarg.type_comment,
                    node.args.kwarg.lineno,
                    0,
                    "type_comment",
                )

        self._process_string_annotation(node.returns)
        for arg in all_args:
            self._process_string_annotation(arg.annotation)
        if node.args.vararg:
            self._process_string_annotation(node.args.vararg.annotation)
        if node.args.kwarg:
            self._process_string_annotation(node.args.kwarg.annotation)

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if node.type_comment:
            # Type comment on assignment - need to find "# type:" position
            self._process_type_string(
                node.type_comment, node.lineno, 0, "type_comment",
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Process string annotation on annotated assignment
        self._process_string_annotation(node.annotation)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if node.type_comment:
            self._process_type_string(
                node.type_comment, node.lineno, 0, "type_comment",
            )
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        if node.type_comment:
            self._process_type_string(
                node.type_comment, node.lineno, 0, "type_comment",
            )
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        if node.type_comment:
            self._process_type_string(
                node.type_comment, node.lineno, 0, "type_comment",
            )
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        if node.type_comment:
            self._process_type_string(
                node.type_comment, node.lineno, 0, "type_comment",
            )
        self.generic_visit(node)


def collect_type_string_attr_usages(
    tree: ast.AST,
    module_imports: set[str],
) -> list[TypeStringAttrUsage]:
    """Collect module.attr usages from type comments and string annotations."""
    visitor = TypeStringAttributeCollector(module_imports)
    visitor.visit(tree)
    return visitor.usages


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
