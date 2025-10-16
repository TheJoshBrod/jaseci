"""ECMAScript AST Generation Pass for the Jac compiler.

This pass transforms the Jac AST into equivalent ECMAScript AST following
the ESTree specification by:

1. Traversing the Jac AST and generating corresponding ESTree nodes
2. Handling all Jac language constructs and translating them to JavaScript/ECMAScript equivalents:
   - Classes, functions, and methods
   - Control flow statements (if/else, loops, try/catch)
   - Data structures (arrays, objects)
   - Special Jac features (walkers, abilities, archetypes) converted to JS classes
   - Data spatial operations converted to appropriate JS patterns

3. Managing imports and module dependencies
4. Preserving source location information
5. Generating valid ECMAScript code that can be executed in JavaScript environments

The output of this pass is a complete ESTree AST representation that can be
serialized to JavaScript source code or used by JavaScript tooling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Union

import jaclang.compiler.passes.ecmascript.estree as es
import jaclang.compiler.unitree as uni
from jaclang.compiler.constant import Tokens as Tok
from jaclang.compiler.passes import UniPass
from jaclang.compiler.passes.ecmascript.es_unparse import es_to_js


@dataclass
class ScopeInfo:
    """Track declarations within a lexical scope."""

    node: uni.UniScopeNode
    declared: set[str] = field(default_factory=set)
    hoisted: list[es.Statement] = field(default_factory=list)


@dataclass
class AssignmentTargetInfo:
    """Container for processed assignment targets."""

    node: uni.UniNode
    left: Union[es.Pattern, es.Expression]
    reference: Optional[es.Expression]
    decl_name: Optional[str]
    pattern_names: list[tuple[str, uni.Name]]
    is_first: bool


class EsastGenPass(UniPass):
    """Jac to ECMAScript AST transpilation pass."""

    def before_pass(self) -> None:
        """Initialize the pass."""
        from jaclang.compiler.codeinfo import ClientManifest

        self.imports: list[es.ImportDeclaration] = []
        self.exports: list[es.ExportNamedDeclaration] = []
        self.scope_stack: list[ScopeInfo] = []
        self.scope_map: dict[uni.UniScopeNode, ScopeInfo] = {}
        self.client_manifest = ClientManifest()

    def enter_node(self, node: uni.UniNode) -> None:
        """Enter node."""
        if isinstance(node, uni.UniScopeNode):
            self._push_scope(node)
        if node.gen.es_ast:
            self.prune()
            return
        super().enter_node(node)

    def exit_node(self, node: uni.UniNode) -> None:
        """Exit node."""
        super().exit_node(node)
        if isinstance(node, uni.UniScopeNode):
            self._pop_scope(node)

    def sync_loc(
        self, es_node: es.Node, jac_node: Optional[uni.UniNode] = None
    ) -> es.Node:
        """Sync source locations from Jac node to ES node."""
        if not jac_node:
            jac_node = self.cur_node
        es_node.loc = es.SourceLocation(
            start=es.Position(
                line=jac_node.loc.first_line, column=jac_node.loc.col_start
            ),
            end=es.Position(line=jac_node.loc.last_line, column=jac_node.loc.col_end),
        )
        return es_node

    def flatten(
        self, items: list[Union[es.Statement, list[es.Statement], None]]
    ) -> list[es.Statement]:
        """Flatten a list of items or lists into a single list."""
        result: list[es.Statement] = []
        for item in items:
            if isinstance(item, list):
                result.extend(item)
            elif item is not None:
                result.append(item)
        return result

    # Scope helpers
    # =============

    def _push_scope(self, node: uni.UniScopeNode) -> None:
        """Enter a new lexical scope."""
        info = ScopeInfo(node=node)
        self.scope_stack.append(info)
        self.scope_map[node] = info

    def _pop_scope(self, node: uni.UniScopeNode) -> None:
        """Exit a lexical scope."""
        if self.scope_stack and self.scope_stack[-1].node is node:
            self.scope_stack.pop()
        self.scope_map.pop(node, None)

    def _current_scope(self) -> Optional[ScopeInfo]:
        """Get the scope currently being populated."""
        return self.scope_stack[-1] if self.scope_stack else None

    def _is_declared_in_current_scope(self, name: str) -> bool:
        """Check if a name is already declared in the active scope."""
        scope = self._current_scope()
        return name in scope.declared if scope else False

    def _register_declaration(self, name: str) -> None:
        """Mark a name as declared within the current scope."""
        scope = self._current_scope()
        if scope:
            scope.declared.add(name)

    def _ensure_identifier_declared(self, name: str, jac_node: uni.UniNode) -> None:
        """Hoist a declaration for identifiers introduced mid-expression (e.g., walrus)."""
        scope = self._current_scope()
        if not scope or name in scope.declared:
            return
        ident = self.sync_loc(es.Identifier(name=name), jac_node=jac_node)
        declarator = self.sync_loc(
            es.VariableDeclarator(id=ident, init=None), jac_node=jac_node
        )
        decl = self.sync_loc(
            es.VariableDeclaration(declarations=[declarator], kind="let"),
            jac_node=jac_node,
        )
        scope.hoisted.append(decl)
        scope.declared.add(name)

    def _prepend_hoisted(
        self, node: uni.UniScopeNode, statements: list[es.Statement]
    ) -> list[es.Statement]:
        """Insert hoisted declarations, if any, ahead of the given statements."""
        scope = self.scope_map.get(node)
        if scope and scope.hoisted:
            hoisted = list(scope.hoisted)
            scope.hoisted.clear()
            return hoisted + statements
        return statements

    # Module and Program
    # ==================

    def exit_module(self, node: uni.Module) -> None:
        """Process module node."""
        body: list[Union[es.Statement, es.ModuleDeclaration]] = []

        # Add imports
        body.extend(self.imports)

        # Insert hoisted declarations (e.g., walrus-introduced identifiers)
        scope = self.scope_map.get(node)
        if scope and scope.hoisted:
            hoisted = list(scope.hoisted)
            scope.hoisted.clear()
            body.extend(hoisted)

        # Process module body
        clean_body = [i for i in node.body if not isinstance(i, uni.ImplDef)]
        client_items: list[Union[es.Statement, list[es.Statement]]] = []
        fallback_items: list[Union[es.Statement, list[es.Statement]]] = []
        for stmt in clean_body:
            if stmt.gen.es_ast:
                target_list = (
                    client_items
                    if getattr(stmt, "is_client_decl", False)
                    else fallback_items
                )
                target_list.append(stmt.gen.es_ast)
        target_body = client_items if client_items else fallback_items
        for item in target_body:
            if isinstance(item, list):
                body.extend(item)
            else:
                body.append(item)

        # Add exports
        body.extend(self.exports)

        program = self.sync_loc(
            es.Program(body=body, sourceType="module"), jac_node=node
        )
        node.gen.es_ast = program

        # Generate JavaScript code from ES AST
        node.gen.js = es_to_js(node.gen.es_ast)

        # Sort and assign client manifest
        self.client_manifest.exports.sort()
        self.client_manifest.globals.sort()
        node.gen.client_manifest = self.client_manifest

    def exit_sub_tag(self, node: uni.SubTag[uni.T]) -> None:
        """Process SubTag node."""
        if node.tag.gen.es_ast:
            node.gen.es_ast = node.tag.gen.es_ast

    # Import/Export Statements
    # ========================

    def exit_import(self, node: uni.Import) -> None:
        """Process import statement."""
        if node.from_loc and node.items:
            source = self.sync_loc(
                es.Literal(value=node.from_loc.dot_path_str), jac_node=node.from_loc
            )
            specifiers: list[
                Union[
                    es.ImportSpecifier,
                    es.ImportDefaultSpecifier,
                    es.ImportNamespaceSpecifier,
                ]
            ] = []

            for item in node.items:
                if isinstance(item, uni.ModuleItem):
                    imported = self.sync_loc(
                        es.Identifier(name=item.name.sym_name), jac_node=item.name
                    )
                    local = self.sync_loc(
                        es.Identifier(
                            name=(
                                item.alias.sym_name
                                if item.alias
                                else item.name.sym_name
                            )
                        ),
                        jac_node=item.alias if item.alias else item.name,
                    )
                    specifiers.append(
                        self.sync_loc(
                            es.ImportSpecifier(imported=imported, local=local),
                            jac_node=item,
                        )
                    )

            import_decl = self.sync_loc(
                es.ImportDeclaration(specifiers=specifiers, source=source),
                jac_node=node,
            )
            self.imports.append(import_decl)
            node.gen.es_ast = []  # Imports are added to module level

    def exit_module_path(self, node: uni.ModulePath) -> None:
        """Process module path."""
        node.gen.es_ast = None

    def exit_module_item(self, node: uni.ModuleItem) -> None:
        """Process module item."""
        node.gen.es_ast = None

    # Declarations
    # ============

    def exit_archetype(self, node: uni.Archetype) -> None:
        """Process archetype (class) declaration."""
        if getattr(node, "is_client_decl", False):
            self.client_manifest.has_client = True
            self.client_manifest.exports.append(node.name.sym_name)

        body_stmts: list[
            Union[es.MethodDefinition, es.PropertyDefinition, es.StaticBlock]
        ] = []
        has_members: list[uni.ArchHas] = []

        # Process body
        inner: Sequence[uni.CodeBlockStmt] | None = None
        if isinstance(node.body, uni.ImplDef) and isinstance(node.body.body, list):
            inner = node.body.body  # type: ignore
        elif isinstance(node.body, list):
            inner = node.body

        if inner:
            for stmt in inner:
                if isinstance(stmt, uni.ArchHas):
                    has_members.append(stmt)
                    continue
                if (
                    stmt.gen.es_ast
                    and stmt.gen.es_ast
                    and isinstance(
                        stmt.gen.es_ast,
                        (es.MethodDefinition, es.PropertyDefinition, es.StaticBlock),
                    )
                ):
                    body_stmts.append(stmt.gen.es_ast)

        if node.arch_type.name == Tok.KW_OBJECT and has_members:
            constructor_stmts: list[es.Statement] = []
            props_param = self.sync_loc(
                es.AssignmentPattern(
                    left=self.sync_loc(es.Identifier(name="props"), jac_node=node),
                    right=self.sync_loc(
                        es.ObjectExpression(properties=[]), jac_node=node
                    ),
                ),
                jac_node=node,
            )

            for arch_has in has_members:
                if arch_has.is_static:
                    for var in arch_has.vars:
                        default_expr = (
                            var.value.gen.es_ast
                            if var.value
                            and var.value.gen.es_ast
                            and var.value.gen.es_ast
                            else self.sync_loc(es.Literal(value=None), jac_node=var)
                        )
                        static_prop = self.sync_loc(
                            es.PropertyDefinition(
                                key=self.sync_loc(
                                    es.Identifier(name=var.name.sym_name),
                                    jac_node=var.name,
                                ),
                                value=default_expr,
                                static=True,
                            ),
                            jac_node=var,
                        )
                        body_stmts.append(static_prop)
                    continue

                for var in arch_has.vars:
                    props_ident = self.sync_loc(
                        es.Identifier(name="props"), jac_node=var
                    )
                    prop_ident = self.sync_loc(
                        es.Identifier(name=var.name.sym_name), jac_node=var.name
                    )
                    this_member = self.sync_loc(
                        es.MemberExpression(
                            object=self.sync_loc(es.ThisExpression(), jac_node=var),
                            property=prop_ident,
                            computed=False,
                        ),
                        jac_node=var,
                    )
                    props_access = self.sync_loc(
                        es.MemberExpression(
                            object=props_ident,
                            property=self.sync_loc(
                                es.Identifier(name=var.name.sym_name),
                                jac_node=var.name,
                            ),
                            computed=False,
                        ),
                        jac_node=var,
                    )
                    has_call = self.sync_loc(
                        es.CallExpression(
                            callee=self.sync_loc(
                                es.MemberExpression(
                                    object=props_ident,
                                    property=self.sync_loc(
                                        es.Identifier(name="hasOwnProperty"),
                                        jac_node=var,
                                    ),
                                    computed=False,
                                ),
                                jac_node=var,
                            ),
                            arguments=[
                                self.sync_loc(
                                    es.Literal(value=var.name.sym_name),
                                    jac_node=var.name,
                                )
                            ],
                        ),
                        jac_node=var,
                    )
                    default_expr = (
                        var.value.gen.es_ast
                        if var.value and var.value.gen.es_ast and var.value.gen.es_ast
                        else self.sync_loc(es.Literal(value=None), jac_node=var)
                    )
                    conditional = self.sync_loc(
                        es.ConditionalExpression(
                            test=has_call,
                            consequent=props_access,
                            alternate=default_expr,
                        ),
                        jac_node=var,
                    )
                    assignment = self.sync_loc(
                        es.AssignmentExpression(
                            operator="=", left=this_member, right=conditional
                        ),
                        jac_node=var,
                    )
                    constructor_stmts.append(
                        self.sync_loc(
                            es.ExpressionStatement(expression=assignment),
                            jac_node=var,
                        )
                    )

            if constructor_stmts:
                constructor_method = self.sync_loc(
                    es.MethodDefinition(
                        key=self.sync_loc(
                            es.Identifier(name="constructor"), jac_node=node
                        ),
                        value=self.sync_loc(
                            es.FunctionExpression(
                                id=None,
                                params=[props_param],
                                body=self.sync_loc(
                                    es.BlockStatement(body=constructor_stmts),
                                    jac_node=node,
                                ),
                            ),
                            jac_node=node,
                        ),
                        kind="constructor",
                        static=False,
                    ),
                    jac_node=node,
                )
                body_stmts.insert(0, constructor_method)

        # Create class body
        class_body = self.sync_loc(es.ClassBody(body=body_stmts), jac_node=node)

        # Handle base classes
        super_class: Optional[es.Expression] = None
        if node.base_classes:
            base = node.base_classes[0]
            if base.gen.es_ast:
                super_class = base.gen.es_ast

        # Create class declaration
        class_id = self.sync_loc(
            es.Identifier(name=node.name.sym_name), jac_node=node.name
        )

        class_decl = self.sync_loc(
            es.ClassDeclaration(id=class_id, superClass=super_class, body=class_body),
            jac_node=node,
        )

        node.gen.es_ast = class_decl

    def exit_enum(self, node: uni.Enum) -> None:
        """Process enum declaration as an object."""
        properties: list[es.Property] = []

        inner: Sequence[uni.EnumBlockStmt] | None = None
        if isinstance(node.body, uni.ImplDef) and isinstance(node.body.body, list):
            inner = node.body.body  # type: ignore
        elif isinstance(node.body, list):
            inner = node.body

        if inner:
            for stmt in inner:
                if isinstance(stmt, uni.Assignment):
                    for target in stmt.target:
                        if isinstance(target, uni.AstSymbolNode):
                            key = self.sync_loc(
                                es.Identifier(name=target.sym_name), jac_node=target
                            )
                            value: es.Expression
                            if stmt.value and stmt.value.gen.es_ast:
                                value = stmt.value.gen.es_ast
                            else:
                                value = self.sync_loc(
                                    es.Literal(value=None), jac_node=stmt
                                )
                            prop = self.sync_loc(
                                es.Property(key=key, value=value, kind="init"),
                                jac_node=stmt,
                            )
                            properties.append(prop)

        # Create as const variable with object
        obj_expr = self.sync_loc(
            es.ObjectExpression(properties=properties), jac_node=node
        )
        var_id = self.sync_loc(
            es.Identifier(name=node.name.sym_name), jac_node=node.name
        )
        var_decl = self.sync_loc(
            es.VariableDeclaration(
                declarations=[
                    self.sync_loc(
                        es.VariableDeclarator(id=var_id, init=obj_expr), jac_node=node
                    )
                ],
                kind="const",
            ),
            jac_node=node,
        )

        node.gen.es_ast = var_decl

    def exit_ability(self, node: uni.Ability) -> None:
        """Process ability (function/method) declaration."""
        if getattr(node, "is_client_decl", False) and not node.is_method:
            self.client_manifest.has_client = True
            name = node.name_ref.sym_name
            self.client_manifest.exports.append(name)
            self.client_manifest.params[name] = (
                [p.name.sym_name for p in node.signature.params if hasattr(p, "name")]
                if isinstance(node.signature, uni.FuncSignature)
                else []
            )

        params: list[es.Pattern] = []
        if isinstance(node.signature, uni.FuncSignature):
            for param in node.signature.params:
                if param.gen.es_ast:
                    params.append(param.gen.es_ast)

        # Process body
        body_stmts: list[es.Statement] = []
        inner: Sequence[uni.CodeBlockStmt] | None = None
        if isinstance(node.body, uni.ImplDef) and isinstance(node.body.body, list):
            inner = node.body.body  # type: ignore
        elif isinstance(node.body, list):
            inner = node.body

        if inner:
            for stmt in inner:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

        body_stmts = self._prepend_hoisted(node, body_stmts)
        block = self.sync_loc(es.BlockStatement(body=body_stmts), jac_node=node)

        func_id = self.sync_loc(
            es.Identifier(name=node.name_ref.sym_name), jac_node=node.name_ref
        )

        # Check if this is a method (has parent archetype)
        if node.is_method:
            # Create method definition
            func_expr = self.sync_loc(
                es.FunctionExpression(
                    id=None, params=params, body=block, async_=node.is_async
                ),
                jac_node=node,
            )
            method_def = self.sync_loc(
                es.MethodDefinition(
                    key=func_id, value=func_expr, kind="method", static=node.is_static
                ),
                jac_node=node,
            )
            node.gen.es_ast = method_def
        else:
            # Create function declaration
            func_decl = self.sync_loc(
                es.FunctionDeclaration(
                    id=func_id, params=params, body=block, async_=node.is_async
                ),
                jac_node=node,
            )
            node.gen.es_ast = func_decl

    def exit_func_signature(self, node: uni.FuncSignature) -> None:
        """Process function signature."""
        node.gen.es_ast = None

    def exit_param_var(self, node: uni.ParamVar) -> None:
        """Process parameter variable."""
        param_id = self.sync_loc(
            es.Identifier(name=node.name.sym_name), jac_node=node.name
        )
        self._register_declaration(param_id.name)
        node.gen.es_ast = param_id

    def exit_arch_has(self, node: uni.ArchHas) -> None:
        """Process class field declarations."""
        # ES doesn't directly support field declarations in the same way
        # This could be handled via constructor assignments
        node.gen.es_ast = None

    def exit_has_var(self, node: uni.HasVar) -> None:
        """Process has variable."""
        node.gen.es_ast = None

    # JSX Nodes
    # =========

    def exit_jsx_element(self, node: uni.JsxElement) -> None:
        """Process JSX element into __jacJsx(tag, props, children) call."""
        # Tag expression (string literal for HTML tags, identifier/member for components)
        if node.is_fragment or not node.name:
            tag_expr: es.Expression = self.sync_loc(
                es.Literal(value=None), jac_node=node
            )
        else:
            tag_expr = (
                node.name.gen.es_ast
                if node.name.gen.es_ast
                else self.sync_loc(es.Literal(value=None), jac_node=node.name)
            )

        # Props / attributes
        props_expr: es.Expression
        attributes = node.attributes or []
        has_spread = any(
            isinstance(attr, uni.JsxSpreadAttribute) for attr in attributes
        )
        if not attributes:
            props_expr = self.sync_loc(
                es.ObjectExpression(properties=[]), jac_node=node
            )
        elif has_spread:
            segments: list[es.Expression] = []
            for attr in attributes:
                if isinstance(attr, uni.JsxSpreadAttribute):
                    exp = getattr(attr.gen, "es_ast", None)
                    if exp:
                        segments.append(exp)
                elif isinstance(attr, uni.JsxNormalAttribute):
                    prop = getattr(attr.gen, "es_ast", None)
                    if isinstance(prop, es.Property):
                        segments.append(
                            self.sync_loc(
                                es.ObjectExpression(properties=[prop]), jac_node=attr
                            )
                        )
            if segments:
                assign_member = self.sync_loc(
                    es.MemberExpression(
                        object=self.sync_loc(
                            es.Identifier(name="Object"), jac_node=node
                        ),
                        property=self.sync_loc(
                            es.Identifier(name="assign"), jac_node=node
                        ),
                        computed=False,
                        optional=False,
                    ),
                    jac_node=node,
                )
                props_expr = self.sync_loc(
                    es.CallExpression(
                        callee=assign_member,
                        arguments=[
                            self.sync_loc(
                                es.ObjectExpression(properties=[]), jac_node=node
                            ),
                            *segments,
                        ],
                    ),
                    jac_node=node,
                )
            else:
                props_expr = self.sync_loc(
                    es.ObjectExpression(properties=[]), jac_node=node
                )
        else:
            properties: list[es.Property] = []
            for attr in attributes:
                prop = getattr(attr.gen, "es_ast", None)
                if isinstance(prop, es.Property):
                    properties.append(prop)
            props_expr = self.sync_loc(
                es.ObjectExpression(properties=properties), jac_node=node
            )

        # Children
        children_elements: list[Optional[Union[es.Expression, es.SpreadElement]]] = []
        for child in node.children or []:
            child_expr = getattr(child.gen, "es_ast", None)
            if child_expr is None:
                continue
            if isinstance(child_expr, list):
                children_elements.extend(child_expr)  # type: ignore[arg-type]
            else:
                children_elements.append(child_expr)
        children_expr = self.sync_loc(
            es.ArrayExpression(elements=children_elements), jac_node=node
        )

        # __jacJsx(tag, props, children)
        call_expr = self.sync_loc(
            es.CallExpression(
                callee=self.sync_loc(es.Identifier(name="__jacJsx"), jac_node=node),
                arguments=[tag_expr, props_expr, children_expr],
            ),
            jac_node=node,
        )
        node.gen.es_ast = call_expr

    def exit_jsx_element_name(self, node: uni.JsxElementName) -> None:
        """Process JSX element name."""
        if not node.parts:
            node.gen.es_ast = self.sync_loc(es.Literal(value=None), jac_node=node)
            return

        parts = [part.value for part in node.parts]
        first = parts[0]
        if first and first[0].isupper():
            expr: es.Expression = self.sync_loc(
                es.Identifier(name=first), jac_node=node.parts[0]
            )
            for idx, part in enumerate(parts[1:], start=1):
                expr = self.sync_loc(
                    es.MemberExpression(
                        object=expr,
                        property=self.sync_loc(
                            es.Identifier(name=part), jac_node=node.parts[idx]
                        ),
                        computed=False,
                        optional=False,
                    ),
                    jac_node=node,
                )
            node.gen.es_ast = expr
        else:
            node.gen.es_ast = self.sync_loc(
                es.Literal(value=".".join(parts)), jac_node=node
            )

    def exit_jsx_spread_attribute(self, node: uni.JsxSpreadAttribute) -> None:
        """Process JSX spread attribute."""
        expr = (
            node.expr.gen.es_ast
            if node.expr.gen.es_ast
            else self.sync_loc(es.ObjectExpression(properties=[]), jac_node=node)
        )
        node.gen.es_ast = expr

    def exit_jsx_normal_attribute(self, node: uni.JsxNormalAttribute) -> None:
        """Process JSX normal attribute."""
        key_expr = self.sync_loc(es.Literal(value=node.name.value), jac_node=node.name)
        if node.value is None:
            value_expr = self.sync_loc(es.Literal(value=True), jac_node=node)
        elif isinstance(node.value, uni.String):
            value_expr = self.sync_loc(
                es.Literal(value=node.value.lit_value), jac_node=node.value
            )
        else:
            value_expr = (
                node.value.gen.es_ast
                if node.value.gen.es_ast
                else self.sync_loc(es.Literal(value=None), jac_node=node.value)
            )

        prop = self.sync_loc(
            es.Property(
                key=key_expr,
                value=value_expr,
                kind="init",
                method=False,
                shorthand=False,
                computed=False,
            ),
            jac_node=node,
        )
        node.gen.es_ast = prop

    def exit_jsx_text(self, node: uni.JsxText) -> None:
        """Process JSX text node."""
        raw_value = node.value.value if hasattr(node.value, "value") else node.value
        node.gen.es_ast = self.sync_loc(es.Literal(value=str(raw_value)), jac_node=node)

    def exit_jsx_expression(self, node: uni.JsxExpression) -> None:
        """Process JSX expression child."""
        expr = (
            node.expr.gen.es_ast
            if node.expr.gen.es_ast
            else self.sync_loc(es.Literal(value=None), jac_node=node.expr)
        )
        node.gen.es_ast = expr

    # Control Flow Statements
    # =======================

    def exit_if_stmt(self, node: uni.IfStmt) -> None:
        """Process if statement."""
        test = (
            node.condition.gen.es_ast
            if node.condition.gen.es_ast
            else self.sync_loc(es.Literal(value=True), jac_node=node.condition)
        )

        consequent_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        consequent_stmts.extend(stmt.gen.es_ast)
                    else:
                        consequent_stmts.append(stmt.gen.es_ast)

        consequent_stmts = self._prepend_hoisted(node, consequent_stmts)
        consequent = self.sync_loc(
            es.BlockStatement(body=consequent_stmts), jac_node=node
        )

        alternate: Optional[es.Statement] = None
        if node.else_body and node.else_body.gen.es_ast and node.else_body.gen.es_ast:
            alternate = node.else_body.gen.es_ast

        if_stmt = self.sync_loc(
            es.IfStatement(test=test, consequent=consequent, alternate=alternate),
            jac_node=node,
        )
        node.gen.es_ast = if_stmt

    def exit_else_if(self, node: uni.ElseIf) -> None:
        """Process else-if clause."""
        test = (
            node.condition.gen.es_ast
            if node.condition.gen.es_ast
            else self.sync_loc(es.Literal(value=True), jac_node=node.condition)
        )

        consequent_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        consequent_stmts.extend(stmt.gen.es_ast)
                    else:
                        consequent_stmts.append(stmt.gen.es_ast)

        consequent_stmts = self._prepend_hoisted(node, consequent_stmts)
        consequent = self.sync_loc(
            es.BlockStatement(body=consequent_stmts), jac_node=node
        )

        alternate: Optional[es.Statement] = None
        if node.else_body and node.else_body.gen.es_ast and node.else_body.gen.es_ast:
            alternate = node.else_body.gen.es_ast

        if_stmt = self.sync_loc(
            es.IfStatement(test=test, consequent=consequent, alternate=alternate),
            jac_node=node,
        )
        node.gen.es_ast = if_stmt

    def exit_else_stmt(self, node: uni.ElseStmt) -> None:
        """Process else clause."""
        stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        stmts.extend(stmt.gen.es_ast)
                    else:
                        stmts.append(stmt.gen.es_ast)

        stmts = self._prepend_hoisted(node, stmts)
        block = self.sync_loc(es.BlockStatement(body=stmts), jac_node=node)
        node.gen.es_ast = block

    def exit_while_stmt(self, node: uni.WhileStmt) -> None:
        """Process while statement."""
        test = (
            node.condition.gen.es_ast
            if node.condition.gen.es_ast
            else self.sync_loc(es.Literal(value=True), jac_node=node.condition)
        )

        body_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

        body_stmts = self._prepend_hoisted(node, body_stmts)
        body = self.sync_loc(es.BlockStatement(body=body_stmts), jac_node=node)

        while_stmt = self.sync_loc(
            es.WhileStatement(test=test, body=body), jac_node=node
        )
        node.gen.es_ast = while_stmt

    def exit_in_for_stmt(self, node: uni.InForStmt) -> None:
        """Process for-in statement."""
        left = (
            node.target.gen.es_ast
            if node.target.gen.es_ast
            else self.sync_loc(es.Identifier(name="item"), jac_node=node.target)
        )
        right = (
            node.collection.gen.es_ast
            if node.collection.gen.es_ast
            else self.sync_loc(
                es.Identifier(name="collection"), jac_node=node.collection
            )
        )

        body_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

        body_stmts = self._prepend_hoisted(node, body_stmts)
        body = self.sync_loc(es.BlockStatement(body=body_stmts), jac_node=node)

        pattern_nodes = (
            es.Identifier,
            es.ArrayPattern,
            es.ObjectPattern,
            es.AssignmentPattern,
            es.RestElement,
        )
        if isinstance(left, es.VariableDeclaration):
            decl = left
        else:
            if isinstance(left, pattern_nodes):
                pattern = left
            else:
                pattern = self.sync_loc(
                    es.Identifier(name="_item"), jac_node=node.target
                )
            declarator = self.sync_loc(
                es.VariableDeclarator(id=pattern, init=None), jac_node=node.target
            )
            decl = self.sync_loc(
                es.VariableDeclaration(
                    declarations=[declarator],
                    kind="const",
                ),
                jac_node=node.target,
            )

        # Use for-of for iteration over values
        for_stmt = self.sync_loc(
            es.ForOfStatement(left=decl, right=right, body=body, await_=node.is_async),
            jac_node=node,
        )
        node.gen.es_ast = for_stmt

    def exit_try_stmt(self, node: uni.TryStmt) -> None:
        """Process try statement."""
        block_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        block_stmts.extend(stmt.gen.es_ast)
                    else:
                        block_stmts.append(stmt.gen.es_ast)

        block_stmts = self._prepend_hoisted(node, block_stmts)
        block = self.sync_loc(es.BlockStatement(body=block_stmts), jac_node=node)

        handler: Optional[es.CatchClause] = None
        if node.excepts:
            # Take first except clause
            except_node = node.excepts[0]
            if except_node.gen.es_ast:
                handler = except_node.gen.es_ast

        finalizer: Optional[es.BlockStatement] = None
        if (
            node.finally_body
            and node.finally_body.gen.es_ast
            and isinstance(node.finally_body.gen.es_ast, es.BlockStatement)
        ):
            finalizer = node.finally_body.gen.es_ast

        try_stmt = self.sync_loc(
            es.TryStatement(block=block, handler=handler, finalizer=finalizer),
            jac_node=node,
        )
        node.gen.es_ast = try_stmt

    def exit_except(self, node: uni.Except) -> None:
        """Process except clause."""
        param: Optional[es.Pattern] = None
        if node.name:
            param = self.sync_loc(
                es.Identifier(name=node.name.sym_name), jac_node=node.name
            )

        body_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

        body_stmts = self._prepend_hoisted(node, body_stmts)
        body = self.sync_loc(es.BlockStatement(body=body_stmts), jac_node=node)

        catch_clause = self.sync_loc(
            es.CatchClause(param=param, body=body), jac_node=node
        )
        node.gen.es_ast = catch_clause

    def exit_finally_stmt(self, node: uni.FinallyStmt) -> None:
        """Process finally clause."""
        body_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

        body_stmts = self._prepend_hoisted(node, body_stmts)
        block = self.sync_loc(es.BlockStatement(body=body_stmts), jac_node=node)
        node.gen.es_ast = block

    def exit_raise_stmt(self, node: uni.RaiseStmt) -> None:
        """Process raise statement."""
        argument = (
            node.cause.gen.es_ast
            if node.cause and node.cause.gen.es_ast
            else self.sync_loc(es.Identifier(name="Error"), jac_node=node)
        )

        if isinstance(argument, es.CallExpression):
            callee = argument.callee
            if isinstance(callee, es.Identifier) and callee.name in {
                "Exception",
                "Error",
            }:
                new_expr = self.sync_loc(
                    es.NewExpression(
                        callee=self.sync_loc(
                            es.Identifier(name="Error"), jac_node=node
                        ),
                        arguments=argument.arguments,
                    ),
                    jac_node=node,
                )
                argument = new_expr

        throw_stmt = self.sync_loc(es.ThrowStatement(argument=argument), jac_node=node)
        node.gen.es_ast = throw_stmt

    def exit_assert_stmt(self, node: uni.AssertStmt) -> None:
        """Process assert statement as if-throw."""
        test = (
            node.condition.gen.es_ast
            if node.condition.gen.es_ast
            else self.sync_loc(es.Literal(value=True), jac_node=node.condition)
        )

        # Negate the test (throw if condition is false)
        negated_test = self.sync_loc(
            es.UnaryExpression(operator="!", prefix=True, argument=test), jac_node=node
        )

        error_msg = "Assertion failed"
        if (
            node.error_msg
            and node.error_msg.gen.es_ast
            and isinstance(node.error_msg.gen.es_ast, es.Literal)
        ):
            error_msg = str(node.error_msg.gen.es_ast.value)

        throw_stmt = self.sync_loc(
            es.ThrowStatement(
                argument=self.sync_loc(
                    es.NewExpression(
                        callee=self.sync_loc(
                            es.Identifier(name="Error"), jac_node=node
                        ),
                        arguments=[
                            self.sync_loc(es.Literal(value=error_msg), jac_node=node)
                        ],
                    ),
                    jac_node=node,
                )
            ),
            jac_node=node,
        )

        if_stmt = self.sync_loc(
            es.IfStatement(
                test=negated_test,
                consequent=self.sync_loc(
                    es.BlockStatement(body=[throw_stmt]), jac_node=node
                ),
            ),
            jac_node=node,
        )
        node.gen.es_ast = if_stmt

    def exit_return_stmt(self, node: uni.ReturnStmt) -> None:
        """Process return statement."""
        argument: Optional[es.Expression] = None
        if node.expr and node.expr.gen.es_ast:
            argument = node.expr.gen.es_ast

        ret_stmt = self.sync_loc(es.ReturnStatement(argument=argument), jac_node=node)
        node.gen.es_ast = ret_stmt

    def exit_ctrl_stmt(self, node: uni.CtrlStmt) -> None:
        """Process control statement (break/continue)."""
        if node.ctrl.name == Tok.KW_BREAK:
            stmt = self.sync_loc(es.BreakStatement(), jac_node=node)
        else:  # continue
            stmt = self.sync_loc(es.ContinueStatement(), jac_node=node)
        node.gen.es_ast = stmt

    def exit_expr_stmt(self, node: uni.ExprStmt) -> None:
        """Process expression statement."""
        expr = (
            node.expr.gen.es_ast
            if node.expr.gen.es_ast
            else self.sync_loc(es.Literal(value=None), jac_node=node.expr)
        )

        expr_stmt = self.sync_loc(
            es.ExpressionStatement(expression=expr), jac_node=node
        )
        node.gen.es_ast = expr_stmt

    # Expressions
    # ===========

    def exit_binary_expr(self, node: uni.BinaryExpr) -> None:
        """Process binary expression."""
        left = node.left.gen.es_ast if node.left.gen.es_ast else None
        if not left:
            if isinstance(node.left, uni.Name):
                left = self.sync_loc(
                    es.Identifier(name=node.left.sym_name), jac_node=node.left
                )
            else:
                left = self.sync_loc(es.Literal(value=0), jac_node=node.left)

        right = node.right.gen.es_ast if node.right.gen.es_ast else None
        if not right:
            if isinstance(node.right, uni.Name):
                right = self.sync_loc(
                    es.Identifier(name=node.right.sym_name), jac_node=node.right
                )
            else:
                right = self.sync_loc(es.Literal(value=0), jac_node=node.right)

        op_name = getattr(node.op, "name", None)

        if op_name == Tok.KW_SPAWN:
            spawn_call = self.sync_loc(
                es.CallExpression(
                    callee=self.sync_loc(
                        es.Identifier(name="__jacSpawn"), jac_node=node
                    ),
                    arguments=[left, right],
                ),
                jac_node=node,
            )
            node.gen.es_ast = spawn_call
            return

        # Map Jac operators to JS operators
        op_map = {
            Tok.EE: "===",
            Tok.NE: "!==",
            Tok.LT: "<",
            Tok.GT: ">",
            Tok.LTE: "<=",
            Tok.GTE: ">=",
            Tok.PLUS: "+",
            Tok.MINUS: "-",
            Tok.STAR_MUL: "*",
            Tok.DIV: "/",
            Tok.MOD: "%",
            Tok.BW_AND: "&",
            Tok.BW_OR: "|",
            Tok.BW_XOR: "^",
            Tok.LSHIFT: "<<",
            Tok.RSHIFT: ">>",
        }

        if op_name == Tok.WALRUS_EQ and isinstance(left, es.Identifier):
            self._ensure_identifier_declared(left.name, node.left)
            assign_expr = self.sync_loc(
                es.AssignmentExpression(operator="=", left=left, right=right),
                jac_node=node,
            )
            node.gen.es_ast = assign_expr
            return

        operator = op_map.get(op_name, "+")

        # Check if it's a logical operator
        if op_name in (Tok.KW_AND, Tok.KW_OR):
            logical_op = "&&" if op_name == Tok.KW_AND else "||"
            bin_expr = self.sync_loc(
                es.LogicalExpression(operator=logical_op, left=left, right=right),
                jac_node=node,
            )
        else:
            bin_expr = self.sync_loc(
                es.BinaryExpression(operator=operator, left=left, right=right),
                jac_node=node,
            )

        node.gen.es_ast = bin_expr

    def exit_bool_expr(self, node: uni.BoolExpr) -> None:
        """Process boolean expression (and/or)."""
        # BoolExpr has op and list of values
        if not node.values or len(node.values) < 2:
            node.gen.es_ast = self.sync_loc(es.Literal(value=None), jac_node=node)
            return

        # Get the operator
        logical_op = "&&" if node.op.name == Tok.KW_AND else "||"

        # Build the logical expression from left to right
        result = (
            node.values[0].gen.es_ast
            if node.values[0].gen.es_ast
            else self.sync_loc(es.Literal(value=None), jac_node=node.values[0])
        )

        for val in node.values[1:]:
            right = (
                val.gen.es_ast
                if val.gen.es_ast
                else self.sync_loc(es.Literal(value=None), jac_node=val)
            )
            result = self.sync_loc(
                es.LogicalExpression(operator=logical_op, left=result, right=right),
                jac_node=node,
            )

        node.gen.es_ast = result

    def exit_compare_expr(self, node: uni.CompareExpr) -> None:
        """Process compare expression."""
        # CompareExpr can have multiple comparisons chained: a < b < c
        # Need to convert to: a < b && b < c

        op_map = {
            Tok.EE: "===",
            Tok.NE: "!==",
            Tok.LT: "<",
            Tok.GT: ">",
            Tok.LTE: "<=",
            Tok.GTE: ">=",
            Tok.KW_IN: "in",
            Tok.KW_NIN: "in",  # Will need negation
        }

        if not node.rights or not node.ops:
            # Fallback to simple comparison
            node.gen.es_ast = self.sync_loc(es.Literal(value=True), jac_node=node)
            return

        # Build comparisons
        comparisons: list[es.Expression] = []
        left = (
            node.left.gen.es_ast
            if node.left.gen.es_ast
            else self.sync_loc(es.Identifier(name="left"), jac_node=node.left)
        )

        for _, (op, right_node) in enumerate(zip(node.ops, node.rights)):
            right = (
                right_node.gen.es_ast
                if right_node.gen.es_ast
                else self.sync_loc(es.Identifier(name="right"), jac_node=right_node)
            )
            operator = op_map.get(op.name, "===")

            # Handle 'not in' operator
            if op.name == Tok.KW_NIN:
                bin_expr = self.sync_loc(
                    es.UnaryExpression(
                        operator="!",
                        prefix=True,
                        argument=self.sync_loc(
                            es.BinaryExpression(operator="in", left=left, right=right),
                            jac_node=node,
                        ),
                    ),
                    jac_node=node,
                )
            else:
                bin_expr = self.sync_loc(
                    es.BinaryExpression(operator=operator, left=left, right=right),
                    jac_node=node,
                )

            comparisons.append(bin_expr)
            left = right  # For chained comparisons

        # Combine with && if multiple comparisons
        if len(comparisons) == 1:
            node.gen.es_ast = comparisons[0]
        else:
            result = comparisons[0]
            for comp in comparisons[1:]:
                result = self.sync_loc(
                    es.LogicalExpression(operator="&&", left=result, right=comp),
                    jac_node=node,
                )
            node.gen.es_ast = result

    def exit_unary_expr(self, node: uni.UnaryExpr) -> None:
        """Process unary expression."""
        operand = (
            node.operand.gen.es_ast
            if node.operand.gen.es_ast
            else self.sync_loc(es.Literal(value=0), jac_node=node.operand)
        )

        op_map = {
            Tok.MINUS: "-",
            Tok.PLUS: "+",
            Tok.NOT: "!",
            Tok.BW_NOT: "~",
        }

        operator = op_map.get(node.op.name, "!")

        unary_expr = self.sync_loc(
            es.UnaryExpression(operator=operator, prefix=True, argument=operand),
            jac_node=node,
        )
        node.gen.es_ast = unary_expr

    def _convert_assignment_target(
        self, target: uni.UniNode
    ) -> tuple[
        Union[es.Pattern, es.Expression], Optional[es.Expression], Optional[str]
    ]:
        """Convert a Jac assignment target into an ESTree pattern/expression."""
        if isinstance(target, uni.Name):
            identifier = self.sync_loc(
                es.Identifier(name=target.sym_name), jac_node=target
            )
            return identifier, identifier, target.sym_name

        if isinstance(target, (uni.TupleVal, uni.ListVal)):
            elements: list[Optional[es.Pattern]] = []
            for value in getattr(target, "values", []):
                if value is None:
                    elements.append(None)
                    continue
                pattern, _, _ = self._convert_assignment_target(value)
                elements.append(pattern if isinstance(pattern, es.Pattern) else pattern)
            pattern = self.sync_loc(es.ArrayPattern(elements=elements), jac_node=target)
            return pattern, None, None

        if isinstance(target, uni.DictVal):
            properties: list[es.AssignmentProperty] = []
            for kv in target.kv_pairs:
                if not isinstance(kv, uni.KVPair) or kv.key is None:
                    continue
                key_expr = (
                    kv.key.gen.es_ast
                    if kv.key.gen.es_ast
                    else self.sync_loc(es.Identifier(name="key"), jac_node=kv.key)
                )
                value_pattern, _, _ = self._convert_assignment_target(kv.value)
                assignment = self.sync_loc(
                    es.AssignmentProperty(
                        key=key_expr,
                        value=(
                            value_pattern
                            if isinstance(value_pattern, es.Pattern)
                            else value_pattern
                        ),
                        shorthand=False,
                    ),
                    jac_node=kv,
                )
                properties.append(assignment)
            pattern = self.sync_loc(
                es.ObjectPattern(properties=properties), jac_node=target
            )
            return pattern, None, None

        if isinstance(target, uni.SubTag):
            return self._convert_assignment_target(target.tag)

        left = (
            target.gen.es_ast
            if target.gen.es_ast
            else self.sync_loc(es.Identifier(name="temp"), jac_node=target)
        )
        reference = left if isinstance(left, es.Expression) else None
        return left, reference, None

    def _collect_pattern_names(self, target: uni.UniNode) -> list[tuple[str, uni.Name]]:
        """Collect identifier names from a (possibly nested) destructuring target."""
        names: list[tuple[str, uni.Name]] = []
        if isinstance(target, uni.Name):
            names.append((target.sym_name, target))
        elif isinstance(target, (uni.TupleVal, uni.ListVal)):
            for value in getattr(target, "values", []):
                names.extend(self._collect_pattern_names(value))
        elif isinstance(target, uni.DictVal):
            for kv in target.kv_pairs:
                if isinstance(kv, uni.KVPair):
                    names.extend(self._collect_pattern_names(kv.value))
        elif isinstance(target, uni.SubTag):
            names.extend(self._collect_pattern_names(target.tag))
        return names

    def _is_name_first_definition(self, name_node: uni.Name) -> bool:
        """Determine whether a name node corresponds to the first definition in its scope."""
        sym = getattr(name_node, "sym", None)
        if sym and name_node.name_spec in sym.defn:
            return sym.defn.index(name_node.name_spec) == 0
        return True

    def exit_assignment(self, node: uni.Assignment) -> None:
        """Process assignment expression."""
        if not node.target:
            node.gen.es_ast = None
            return

        aug_op_map = {
            Tok.ADD_EQ: "+=",
            Tok.SUB_EQ: "-=",
            Tok.MUL_EQ: "*=",
            Tok.DIV_EQ: "/=",
            Tok.MOD_EQ: "%=",
            Tok.BW_AND_EQ: "&=",
            Tok.BW_OR_EQ: "|=",
            Tok.BW_XOR_EQ: "^=",
            Tok.LSHIFT_EQ: "<<=",
            Tok.RSHIFT_EQ: ">>=",
            Tok.STAR_POW_EQ: "**=",
        }

        value_expr = (
            node.value.gen.es_ast
            if node.value and node.value.gen.es_ast and node.value.gen.es_ast
            else None
        )

        if node.aug_op:
            left, _, _ = self._convert_assignment_target(node.target[0])
            operator = aug_op_map.get(node.aug_op.name, "=")
            right = value_expr or self.sync_loc(
                es.Identifier(name="undefined"), jac_node=node
            )
            assign_expr = self.sync_loc(
                es.AssignmentExpression(operator=operator, left=left, right=right),
                jac_node=node,
            )
            expr_stmt = self.sync_loc(
                es.ExpressionStatement(expression=assign_expr), jac_node=node
            )
            node.gen.es_ast = expr_stmt
            return

        targets_info: list[AssignmentTargetInfo] = []
        for target_node in node.target:
            left, reference, decl_name = self._convert_assignment_target(target_node)
            pattern_names = self._collect_pattern_names(target_node)
            first_def = False
            if isinstance(target_node, uni.Name):
                first_def = self._is_name_first_definition(target_node)
            elif pattern_names:
                first_def = any(
                    self._is_name_first_definition(name_node)
                    for _, name_node in pattern_names
                )

            targets_info.append(
                AssignmentTargetInfo(
                    node=target_node,
                    left=left,
                    reference=reference,
                    decl_name=decl_name,
                    pattern_names=pattern_names,
                    is_first=first_def,
                )
            )

        statements: list[es.Statement] = []
        current_value = value_expr or self.sync_loc(
            es.Identifier(name="undefined"), jac_node=node
        )

        for info in reversed(targets_info):
            target_node = info.node
            left = info.left
            decl_name = info.decl_name
            pattern_names = info.pattern_names
            is_first = info.is_first

            should_declare = False
            if decl_name:
                should_declare = is_first and not self._is_declared_in_current_scope(
                    decl_name
                )
            elif pattern_names:
                should_declare = any(
                    self._is_name_first_definition(name_node)
                    and not self._is_declared_in_current_scope(name)
                    for name, name_node in pattern_names
                )

            if should_declare:
                declarator = self.sync_loc(
                    es.VariableDeclarator(
                        id=left, init=current_value if value_expr is not None else None
                    ),
                    jac_node=target_node,
                )
                decl_stmt = self.sync_loc(
                    es.VariableDeclaration(
                        declarations=[declarator],
                        kind="let",
                    ),
                    jac_node=target_node,
                )
                statements.append(decl_stmt)

                if decl_name:
                    self._register_declaration(decl_name)
                else:
                    for name, _ in pattern_names:
                        self._register_declaration(name)
            else:
                assign_expr = self.sync_loc(
                    es.AssignmentExpression(
                        operator="=",
                        left=left,
                        right=current_value,
                    ),
                    jac_node=target_node,
                )
                expr_stmt = self.sync_loc(
                    es.ExpressionStatement(expression=assign_expr),
                    jac_node=target_node,
                )
                statements.append(expr_stmt)

            if isinstance(left, es.Identifier):
                current_value = self.sync_loc(
                    es.Identifier(name=left.name), jac_node=target_node
                )
            elif isinstance(info.reference, es.Identifier):
                ref_ident = info.reference
                current_value = self.sync_loc(
                    es.Identifier(name=ref_ident.name), jac_node=target_node
                )
            else:
                current_value = info.reference or current_value

        if len(statements) == 1:
            node.gen.es_ast = statements[0]
        else:
            node.gen.es_ast = statements

    def exit_func_call(self, node: uni.FuncCall) -> None:
        """Process function call."""
        # Special case: type(x) -> typeof x in JavaScript
        # Check the target directly before processing it into an es_ast
        target_is_type = False
        if isinstance(node.target, (uni.Name, uni.BuiltinType)):
            target_name = getattr(node.target, "sym_name", None)
            if target_name == "type":
                target_is_type = True

        args: list[Union[es.Expression, es.SpreadElement]] = []
        for param in node.params:
            if param.gen.es_ast:
                args.append(param.gen.es_ast)

        if target_is_type and len(args) == 1 and isinstance(args[0], es.Expression):
            typeof_expr = self.sync_loc(
                es.UnaryExpression(operator="typeof", prefix=True, argument=args[0]),
                jac_node=node,
            )
            node.gen.es_ast = typeof_expr
            return

        callee = (
            node.target.gen.es_ast
            if node.target.gen.es_ast
            else self.sync_loc(es.Identifier(name="func"), jac_node=node.target)
        )

        if isinstance(callee, es.MemberExpression) and isinstance(
            callee.property, es.Identifier
        ):
            method_map = {
                "lower": "toLowerCase",
                "upper": "toUpperCase",
                "startswith": "startsWith",
                "endswith": "endsWith",
            }
            replacement = method_map.get(callee.property.name)
            if replacement:
                callee = self.sync_loc(
                    es.MemberExpression(
                        object=callee.object,
                        property=self.sync_loc(
                            es.Identifier(name=replacement), jac_node=node
                        ),
                        computed=callee.computed,
                    ),
                    jac_node=node,
                )

        call_expr = self.sync_loc(
            es.CallExpression(callee=callee, arguments=args), jac_node=node
        )
        node.gen.es_ast = call_expr

    def exit_index_slice(self, node: uni.IndexSlice) -> None:
        """Process index/slice - just store the slice info, actual member access is handled by AtomTrailer."""
        # IndexSlice doesn't have a target - it's used within an AtomTrailer
        # Store the slice information for use by the parent AtomTrailer
        if node.slices and len(node.slices) > 0:
            first_slice = node.slices[0]
            if node.is_range:
                # Store slice info - will be used by AtomTrailer
                node.gen.es_ast = {
                    "type": "slice",
                    "start": (
                        first_slice.start.gen.es_ast
                        if first_slice.start and first_slice.start.gen.es_ast
                        else None
                    ),
                    "stop": (
                        first_slice.stop.gen.es_ast
                        if first_slice.stop and first_slice.stop.gen.es_ast
                        else None
                    ),
                }
            else:
                # Store index info - will be used by AtomTrailer
                node.gen.es_ast = {
                    "type": "index",
                    "value": (
                        first_slice.start.gen.es_ast
                        if first_slice.start and first_slice.start.gen.es_ast
                        else self.sync_loc(es.Literal(value=0), jac_node=node)
                    ),
                }
        else:
            node.gen.es_ast = None

    def exit_atom_trailer(self, node: uni.AtomTrailer) -> None:
        """Process attribute access."""
        obj = (
            node.target.gen.es_ast
            if node.target.gen.es_ast
            else self.sync_loc(es.Identifier(name="obj"), jac_node=node.target)
        )

        if node.right and node.right.gen.es_ast:
            # The right side is already processed (could be a call, etc.)
            # Check if it's a Name that needs to become a property access
            if isinstance(node.right, uni.Name):
                prop = self.sync_loc(
                    es.Identifier(name=node.right.sym_name), jac_node=node.right
                )
                member_expr = self.sync_loc(
                    es.MemberExpression(object=obj, property=prop, computed=False),
                    jac_node=node,
                )
                node.gen.es_ast = member_expr
            elif isinstance(node.right, uni.IndexSlice):
                # Handle index/slice operations
                slice_info = node.right.gen.es_ast
                if isinstance(slice_info, dict):
                    if slice_info.get("type") == "slice":
                        # Slice operation - convert to .slice() call
                        start = slice_info.get("start") or self.sync_loc(
                            es.Literal(value=0), jac_node=node
                        )
                        stop = slice_info.get("stop")
                        args: list[es.Expression] = [start]
                        if stop is not None:
                            args.append(stop)
                        slice_call = self.sync_loc(
                            es.CallExpression(
                                callee=self.sync_loc(
                                    es.MemberExpression(
                                        object=obj,
                                        property=self.sync_loc(
                                            es.Identifier(name="slice"), jac_node=node
                                        ),
                                        computed=False,
                                    ),
                                    jac_node=node,
                                ),
                                arguments=args,
                            ),
                            jac_node=node,
                        )
                        node.gen.es_ast = slice_call
                    elif slice_info.get("type") == "index":
                        # Index operation
                        idx = slice_info.get("value") or self.sync_loc(
                            es.Literal(value=0), jac_node=node
                        )
                        member_expr = self.sync_loc(
                            es.MemberExpression(
                                object=obj, property=idx, computed=True
                            ),
                            jac_node=node,
                        )
                        node.gen.es_ast = member_expr
                    else:
                        node.gen.es_ast = obj
                else:
                    node.gen.es_ast = obj
            else:
                # If right is a call or other expression, it should already be processed
                node.gen.es_ast = node.right.gen.es_ast

    def exit_lambda_expr(self, node: uni.LambdaExpr) -> None:
        """Process lambda expression as arrow function."""
        # Extract parameters
        params: list[es.Pattern] = []
        if isinstance(node.signature, uni.FuncSignature):
            for param in node.signature.params:
                if param.gen.es_ast:
                    params.append(param.gen.es_ast)

        # Check if body is a code block or single expression
        if isinstance(node.body, uni.CodeBlockStmt):
            # Multi-statement lambda: use arrow function with block body
            body_stmts: list[es.Statement] = []
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

            body_stmts = self._prepend_hoisted(node.body, body_stmts)
            block_stmt = self.sync_loc(
                es.BlockStatement(body=body_stmts), jac_node=node.body
            )

            arrow_func = self.sync_loc(
                es.ArrowFunctionExpression(
                    params=params, body=block_stmt, async_=False
                ),
                jac_node=node,
            )
            node.gen.es_ast = arrow_func
        else:
            # Single expression lambda: use arrow function with expression body
            body_expr = (
                node.body.gen.es_ast
                if node.body.gen.es_ast
                else self.sync_loc(es.Literal(value=None), jac_node=node.body)
            )

            arrow_func = self.sync_loc(
                es.ArrowFunctionExpression(params=params, body=body_expr, async_=False),
                jac_node=node,
            )
            node.gen.es_ast = arrow_func

    def exit_atom_unit(self, node: uni.AtomUnit) -> None:
        """Process parenthesized atom."""
        # Check if this is an IIFE (Immediately Invoked Function Expression)
        # i.e., a parenthesized function_decl (Ability)
        if isinstance(node.value, uni.Ability) and node.value.gen.es_ast:
            # Convert function declaration to function expression for IIFE
            func_decl = node.value.gen.es_ast
            if isinstance(func_decl, es.FunctionDeclaration):
                # Convert to function expression
                func_expr = self.sync_loc(
                    es.FunctionExpression(
                        id=func_decl.id,
                        params=func_decl.params,
                        body=func_decl.body,
                        async_=func_decl.async_,
                    ),
                    jac_node=node.value,
                )
                node.gen.es_ast = func_expr
            else:
                node.gen.es_ast = node.value.gen.es_ast
        elif node.value and node.value.gen.es_ast:
            node.gen.es_ast = node.value.gen.es_ast
        else:
            node.gen.es_ast = self.sync_loc(es.Literal(value=None), jac_node=node)

    def exit_list_val(self, node: uni.ListVal) -> None:
        """Process list literal."""
        elements: list[Optional[Union[es.Expression, es.SpreadElement]]] = []
        for item in node.values:
            if item.gen.es_ast:
                elements.append(item.gen.es_ast)

        array_expr = self.sync_loc(es.ArrayExpression(elements=elements), jac_node=node)
        node.gen.es_ast = array_expr

    def exit_set_val(self, node: uni.SetVal) -> None:
        """Process set literal as new Set()."""
        elements: list[Union[es.Expression, es.SpreadElement]] = []
        for item in node.values:
            if item.gen.es_ast:
                elements.append(item.gen.es_ast)

        # Create new Set([...])
        set_expr = self.sync_loc(
            es.NewExpression(
                callee=self.sync_loc(es.Identifier(name="Set"), jac_node=node),
                arguments=[
                    self.sync_loc(es.ArrayExpression(elements=elements), jac_node=node)
                ],
            ),
            jac_node=node,
        )
        node.gen.es_ast = set_expr

    def exit_tuple_val(self, node: uni.TupleVal) -> None:
        """Process tuple as array."""
        elements: list[Optional[Union[es.Expression, es.SpreadElement]]] = []
        for item in node.values:
            if item.gen.es_ast:
                elements.append(item.gen.es_ast)

        array_expr = self.sync_loc(es.ArrayExpression(elements=elements), jac_node=node)
        node.gen.es_ast = array_expr

    def exit_dict_val(self, node: uni.DictVal) -> None:
        """Process dictionary literal."""
        properties: list[Union[es.Property, es.SpreadElement]] = []
        for kv_pair in node.kv_pairs:
            if not isinstance(kv_pair, uni.KVPair) or kv_pair.value is None:
                continue

            if kv_pair.key is None:
                if kv_pair.value.gen.es_ast:
                    properties.append(
                        self.sync_loc(
                            es.SpreadElement(argument=kv_pair.value.gen.es_ast),
                            jac_node=kv_pair.value,
                        )
                    )
                continue

            key = (
                kv_pair.key.gen.es_ast
                if kv_pair.key.gen.es_ast
                else self.sync_loc(es.Literal(value="key"), jac_node=kv_pair.key)
            )
            value = (
                kv_pair.value.gen.es_ast
                if kv_pair.value.gen.es_ast
                else self.sync_loc(es.Literal(value=None), jac_node=kv_pair.value)
            )

            prop = self.sync_loc(
                es.Property(key=key, value=value, kind="init"), jac_node=kv_pair
            )
            properties.append(prop)

        obj_expr = self.sync_loc(
            es.ObjectExpression(properties=properties), jac_node=node
        )
        node.gen.es_ast = obj_expr

    def exit_k_v_pair(self, node: uni.KVPair) -> None:
        """Process key-value pair."""
        # Handled in dict_val
        pass

    def exit_inner_compr(self, node: uni.InnerCompr) -> None:
        """Process list comprehension."""
        # List comprehensions need to be converted to functional style
        # [x for x in list] -> list.map(x => x)
        # This is a simplified version
        node.gen.es_ast = self.sync_loc(es.ArrayExpression(elements=[]), jac_node=node)

    # Literals and Atoms
    # ==================

    def exit_bool(self, node: uni.Bool) -> None:
        """Process boolean literal."""
        value = node.value.lower() == "true"
        raw_value = "true" if value else "false"
        bool_lit = self.sync_loc(es.Literal(value=value, raw=raw_value), jac_node=node)
        node.gen.es_ast = bool_lit

    def exit_int(self, node: uni.Int) -> None:
        """Process integer literal."""
        # Use base 0 to auto-detect binary (0b), octal (0o), hex (0x), or decimal
        int_lit = self.sync_loc(
            es.Literal(value=int(node.value, 0), raw=node.value), jac_node=node
        )
        node.gen.es_ast = int_lit

    def exit_float(self, node: uni.Float) -> None:
        """Process float literal."""
        float_lit = self.sync_loc(
            es.Literal(value=float(node.value), raw=node.value), jac_node=node
        )
        node.gen.es_ast = float_lit

    def exit_multi_string(self, node: uni.MultiString) -> None:
        """Process multi-string literal."""
        # MultiString can contain multiple string parts (for concatenation)
        # For now, concatenate them into a single string
        if not node.strings:
            null_lit = self.sync_loc(es.Literal(value="", raw='""'), jac_node=node)
            node.gen.es_ast = null_lit
            return

        # If single string, just use it
        if len(node.strings) == 1:
            string_node = node.strings[0]
            if string_node.gen.es_ast:
                node.gen.es_ast = string_node.gen.es_ast
            else:
                # Fallback: process the string directly (String only, not FString)
                if isinstance(string_node, uni.String):
                    value = string_node.value
                    if value.startswith(('"""', "'''")):
                        value = value[3:-3]
                    elif value.startswith(('"', "'")):
                        value = value[1:-1]
                    str_lit = self.sync_loc(
                        es.Literal(value=value, raw=string_node.value),
                        jac_node=string_node,
                    )
                    node.gen.es_ast = str_lit
                else:
                    # FString should have been processed already
                    node.gen.es_ast = self.sync_loc(es.Literal(value=""), jac_node=node)
            return

        # Multiple strings - create a concatenation expression
        parts = []
        for string_node in node.strings:
            if string_node.gen.es_ast:
                parts.append(string_node.gen.es_ast)
            elif isinstance(string_node, uni.String):
                # Fallback for String nodes only
                value = string_node.value
                if value.startswith(('"""', "'''")):
                    value = value[3:-3]
                elif value.startswith(('"', "'")):
                    value = value[1:-1]
                raw_val = (
                    json.dumps(value) if isinstance(value, str) else string_node.value
                )
                str_lit = self.sync_loc(
                    es.Literal(value=value, raw=raw_val), jac_node=string_node
                )
                parts.append(str_lit)
            # Skip FString nodes that haven't been processed

        if not parts:
            node.gen.es_ast = self.sync_loc(es.Literal(value=""), jac_node=node)
            return

        # Create binary expression for concatenation
        result = parts[0]
        for part in parts[1:]:
            result = self.sync_loc(
                es.BinaryExpression(operator="+", left=result, right=part),
                jac_node=node,
            )
        node.gen.es_ast = result

    def exit_string(self, node: uni.String) -> None:
        """Process string literal."""
        # Remove quotes from the value
        value = node.value
        if value.startswith(('"""', "'''")):
            value = value[3:-3]
        elif value.startswith(('"', "'")):
            value = value[1:-1]

        raw_value = node.value
        if isinstance(value, str):
            raw_value = json.dumps(value)

        str_lit = self.sync_loc(es.Literal(value=value, raw=raw_value), jac_node=node)
        node.gen.es_ast = str_lit

    def exit_f_string(self, node: uni.FString) -> None:
        """Process f-string literal as template literal."""
        # F-strings need to be converted to template literals (backtick strings) in JS
        # f"Hello {name}" -> `Hello ${name}`

        # For now, convert to concatenation of strings and expressions
        # This is a simplified version - proper template literals would be better
        parts: list[es.Expression] = []

        for part in node.parts:
            if part.gen.es_ast:
                expr = part.gen.es_ast
                if isinstance(expr, es.ExpressionStatement):
                    expr = expr.expression
                parts.append(expr)

        if not parts:
            # Empty f-string
            node.gen.es_ast = self.sync_loc(es.Literal(value=""), jac_node=node)
        elif len(parts) == 1:
            # Single part
            node.gen.es_ast = parts[0]
        else:
            # Multiple parts - concatenate with +
            result = parts[0]
            for part in parts[1:]:
                result = self.sync_loc(
                    es.BinaryExpression(operator="+", left=result, right=part),
                    jac_node=node,
                )
            node.gen.es_ast = result

    def exit_if_else_expr(self, node: uni.IfElseExpr) -> None:
        """Process ternary expression."""
        test = (
            node.condition.gen.es_ast
            if node.condition.gen.es_ast
            else self.sync_loc(es.Identifier(name="condition"), jac_node=node.condition)
        )
        consequent = (
            node.value.gen.es_ast
            if node.value.gen.es_ast
            else self.sync_loc(es.Identifier(name="value"), jac_node=node.value)
        )
        alternate = (
            node.else_value.gen.es_ast
            if node.else_value.gen.es_ast
            else self.sync_loc(
                es.Identifier(name="alternate"), jac_node=node.else_value
            )
        )
        cond_expr = self.sync_loc(
            es.ConditionalExpression(
                test=test, consequent=consequent, alternate=alternate
            ),
            jac_node=node,
        )
        node.gen.es_ast = cond_expr

    def exit_await_expr(self, node: uni.AwaitExpr) -> None:
        """Process await expression."""
        argument = (
            node.target.gen.es_ast
            if node.target.gen.es_ast
            else self.sync_loc(es.Identifier(name="undefined"), jac_node=node.target)
        )
        await_expr = self.sync_loc(es.AwaitExpression(argument=argument), jac_node=node)
        node.gen.es_ast = await_expr

    def exit_null(self, node: uni.Null) -> None:
        """Process null/None literal."""
        null_lit = self.sync_loc(es.Literal(value=None, raw="null"), jac_node=node)
        node.gen.es_ast = null_lit

    def exit_name(self, node: uni.Name) -> None:
        """Process name/identifier."""
        # Map Python/Jac names to JS equivalents
        name_map = {
            "None": "null",
            "True": "true",
            "False": "false",
            "self": "this",
        }

        name = name_map.get(node.sym_name, node.sym_name)
        identifier = self.sync_loc(es.Identifier(name=name), jac_node=node)
        node.gen.es_ast = identifier

    # Special Statements
    # ==================

    def exit_global_vars(self, node: uni.GlobalVars) -> None:
        """Process global variables."""
        if getattr(node, "is_client_decl", False):
            self.client_manifest.has_client = True
            for assignment in node.assignments:
                for target in assignment.target:
                    if sym_name := getattr(target, "sym_name", None):
                        self.client_manifest.globals.append(sym_name)
                        if (
                            assignment.value
                            and (lit_val := self._literal_value(assignment.value))
                            is not None
                        ):
                            self.client_manifest.globals_values[sym_name] = lit_val

        statements: list[es.Statement] = []
        for assignment in node.assignments:
            if assignment.gen.es_ast:
                stmt = assignment.gen.es_ast
                if (
                    isinstance(stmt, es.VariableDeclaration)
                    and node.is_frozen
                    and stmt.kind != "const"
                ):
                    stmt.kind = "const"
                statements.append(stmt)
        node.gen.es_ast = statements

    def exit_non_local_vars(self, node: uni.NonLocalVars) -> None:
        """Process non-local variables."""
        # Non-local doesn't have direct equivalent in ES
        node.gen.es_ast = []

    def exit_module_code(self, node: uni.ModuleCode) -> None:
        """Process module code (with entry block)."""
        # Generate the body statements directly
        body_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

        # Module code is executed at module level, so just output the statements
        node.gen.es_ast = body_stmts

    def exit_test(self, node: uni.Test) -> None:
        """Process test as a function."""
        # Convert test to a regular function
        params: list[es.Pattern] = []

        body_stmts: list[es.Statement] = []
        if node.body:
            for stmt in node.body:
                if stmt.gen.es_ast:
                    if isinstance(stmt.gen.es_ast, list):
                        body_stmts.extend(stmt.gen.es_ast)
                    else:
                        body_stmts.append(stmt.gen.es_ast)

        body_stmts = self._prepend_hoisted(node, body_stmts)
        block = self.sync_loc(es.BlockStatement(body=body_stmts), jac_node=node)

        func_id = self.sync_loc(
            es.Identifier(name=node.name.sym_name), jac_node=node.name
        )

        func_decl = self.sync_loc(
            es.FunctionDeclaration(id=func_id, params=params, body=block),
            jac_node=node,
        )
        node.gen.es_ast = func_decl

    # Type and other nodes
    # ====================

    def exit_token(self, node: uni.Token) -> None:
        """Process token."""
        # Tokens are generally not directly converted
        pass

    def exit_semi(self, node: uni.Semi) -> None:
        """Process semicolon."""
        # Semicolons are handled automatically
        pass

    def _literal_value(self, expr: uni.UniNode | None) -> object | None:
        """Extract literal value from an expression."""
        if expr is None:
            return None
        literal_attr = "lit_value"
        if hasattr(expr, literal_attr):
            return getattr(expr, literal_attr)
        if isinstance(expr, uni.MultiString):
            parts: list[str] = []
            for segment in expr.strings:
                if hasattr(segment, literal_attr):
                    parts.append(getattr(segment, literal_attr))
                else:
                    return None
            return "".join(parts)
        if isinstance(expr, uni.ListVal):
            values = [self._literal_value(item) for item in expr.values]
            if all(val is not None for val in values):
                return values
        if isinstance(expr, uni.TupleVal):
            values = [self._literal_value(item) for item in expr.values]
            if all(val is not None for val in values):
                return tuple(values)
        if isinstance(expr, uni.DictVal):
            items: dict[str, Any] = {}
            for pair in expr.kv_pairs:
                if isinstance(pair, uni.KVPair) and pair.key:
                    key_val = self._literal_value(pair.key)
                    val_val = self._literal_value(pair.value)
                    if isinstance(key_val, str) and val_val is not None:
                        items[key_val] = val_val
            if items:
                return items
        return None
