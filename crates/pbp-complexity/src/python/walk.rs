//! The walk the retired complexity_python.py's `Analyzer` made over a module: a pre-order walk in CPython's `ast` field
//! order, so functions come out in the same order, with the reference's visitors where it has one and
//! `ast.iter_child_nodes` everywhere else.

use ruff_python_ast::token::{TokenKind, Tokens};
use ruff_python_ast::{
    BoolOp, Comprehension, ElifElseClause, ExceptHandler, Expr, ExprBoolOp, ExprCall, ExprIf,
    ExprLambda, ExprName, InterpolatedStringElements, Pattern, Stmt, StmtClassDef, StmtFunctionDef,
    StmtMatch, StmtTry, TypeParam, TypeParams,
};
use ruff_text_size::{Ranged, TextSize};

use super::source::Lines;
use crate::scorer::{Function, Scorer, operator_runs};

/// An `if` as CPython nests it: an `elif` is an `If` alone in its parent's `orelse`.
struct If<'a> {
    start: TextSize,
    test: &'a Expr,
    body: &'a [Stmt],
    clauses: &'a [ElifElseClause],
}

/// An `If`'s `orelse` in CPython's shape.
enum OrElse<'a> {
    Empty,
    If(If<'a>),
    Body(&'a [Stmt]),
}

pub struct Analyzer<'a> {
    lines: &'a Lines<'a>,
    tokens: &'a Tokens,
    scorer: Scorer,
    classes: Vec<String>,
}

impl<'a> Analyzer<'a> {
    pub fn new(lines: &'a Lines<'a>, tokens: &'a Tokens) -> Self {
        Analyzer {
            lines,
            tokens,
            scorer: Scorer::default(),
            classes: Vec::new(),
        }
    }

    pub fn finish(self) -> Vec<Function> {
        self.scorer.functions
    }

    pub fn body(&mut self, statements: &'a [Stmt]) {
        for statement in statements {
            self.stmt(statement);
        }
    }

    fn nested_body(&mut self, statements: &'a [Stmt]) {
        let region = self.scorer.enter_nesting();
        self.body(statements);
        self.scorer.leave_nesting(region);
    }

    fn exprs(&mut self, expressions: &'a [Expr]) {
        for expression in expressions {
            self.expr(expression);
        }
    }

    fn optional(&mut self, expression: Option<&'a Expr>) {
        if let Some(expression) = expression {
            self.expr(expression);
        }
    }

    fn stmt(&mut self, statement: &'a Stmt) {
        match statement {
            Stmt::FunctionDef(function) => self.function_def(function),
            Stmt::ClassDef(class) => self.class_def(class),
            Stmt::If(node) => self.if_stmt(
                &If {
                    start: node.start(),
                    test: &node.test,
                    body: &node.body,
                    clauses: &node.elif_else_clauses,
                },
                false,
            ),
            Stmt::For(node) => {
                self.loop_stmt(&[&node.target, &node.iter], &node.body, &node.orelse)
            }
            Stmt::While(node) => self.loop_stmt(&[&node.test], &node.body, &node.orelse),
            Stmt::Try(node) => self.try_stmt(node),
            Stmt::Match(node) => self.match_stmt(node),
            Stmt::With(node) => {
                for item in &node.items {
                    self.expr(&item.context_expr);
                    self.optional(item.optional_vars.as_deref());
                }
                self.body(&node.body);
            }
            _ => self.simple_stmt(statement),
        }
    }

    /// Statements without a body: `ast.iter_child_nodes` over their expressions.
    fn simple_stmt(&mut self, statement: &'a Stmt) {
        match statement {
            Stmt::Return(node) => self.optional(node.value.as_deref()),
            Stmt::Delete(node) => self.exprs(&node.targets),
            Stmt::TypeAlias(node) => {
                self.expr(&node.name);
                self.type_params(node.type_params.as_deref());
                self.expr(&node.value);
            }
            Stmt::Assign(node) => {
                self.exprs(&node.targets);
                self.expr(&node.value);
            }
            Stmt::AugAssign(node) => {
                self.expr(&node.target);
                self.expr(&node.value);
            }
            Stmt::AnnAssign(node) => {
                self.expr(&node.target);
                self.expr(&node.annotation);
                self.optional(node.value.as_deref());
            }
            Stmt::Raise(node) => {
                self.optional(node.exc.as_deref());
                self.optional(node.cause.as_deref());
            }
            Stmt::Assert(node) => {
                self.expr(&node.test);
                self.optional(node.msg.as_deref());
            }
            Stmt::Expr(node) => self.expr(&node.value),
            _ => {}
        }
    }

    fn type_params(&mut self, params: Option<&'a TypeParams>) {
        for param in params.into_iter().flat_map(|params| &params.type_params) {
            match param {
                TypeParam::TypeVar(var) => {
                    self.optional(var.bound.as_deref());
                    self.optional(var.default.as_deref());
                }
                TypeParam::TypeVarTuple(var) => self.optional(var.default.as_deref()),
                TypeParam::ParamSpec(spec) => self.optional(spec.default.as_deref()),
            }
        }
    }

    // Functions and classes

    fn class_def(&mut self, class: &'a StmtClassDef) {
        for decorator in &class.decorator_list {
            self.expr(&decorator.expression);
        }
        if let Some(arguments) = &class.arguments {
            self.exprs(&arguments.args);
            for keyword in &arguments.keywords {
                self.expr(&keyword.value);
            }
        }
        self.classes.push(class.name.to_string());
        self.body(&class.body);
        self.classes.pop();
    }

    /// Decorators and defaults belong to the enclosing scope; annotations, type parameters, and the return
    /// annotation are not walked at all.
    fn function_def(&mut self, function: &'a StmtFunctionDef) {
        for decorator in &function.decorator_list {
            self.expr(&decorator.expression);
        }
        let parameters = &function.parameters;
        for parameter in parameters.posonlyargs.iter().chain(&parameters.args) {
            self.optional(parameter.default());
        }
        for parameter in &parameters.kwonlyargs {
            self.optional(parameter.default());
        }
        let in_class = !self.classes.is_empty() && !self.scorer.active();
        let short = function.name.as_str();
        let (name, own_names) = if in_class {
            let name = format!("{}.{short}", self.classes.join("."));
            (name, vec![format!("self.{short}"), format!("cls.{short}")])
        } else {
            (short.to_owned(), vec![short.to_owned()])
        };
        let line = self.lines.line(self.def_start(function));
        let end_line = self.lines.line(function.end());
        self.scorer.function(name, line, end_line, own_names);
        self.body(&function.body);
        self.scorer.end_function();
    }

    /// CPython numbers a function by its `def` (or `async`), not its first decorator.
    fn def_start(&self, function: &StmtFunctionDef) -> TextSize {
        let Some(last) = function.decorator_list.last() else {
            return function.start();
        };
        self.tokens
            .after(last.end())
            .iter()
            .find(|token| matches!(token.kind(), TokenKind::Def | TokenKind::Async))
            .map_or(function.start(), Ranged::start)
    }

    fn lambda(&mut self, lambda: &'a ExprLambda) {
        let line = self.lines.line(lambda.start());
        let end_line = self.lines.line(lambda.end());
        self.scorer
            .function("<lambda>".to_owned(), line, end_line, Vec::new());
        self.expr(&lambda.body);
        self.scorer.end_function();
    }

    fn call(&mut self, call: &'a ExprCall) {
        match &*call.func {
            Expr::Name(name) => self.scorer.call(name.id.as_str()),
            Expr::Attribute(attribute) => {
                if let Expr::Name(ExprName { id, .. }) = &*attribute.value {
                    self.scorer.call(&format!("{id}.{}", attribute.attr));
                }
            }
            _ => {}
        }
        self.expr(&call.func);
        self.exprs(&call.arguments.args);
        for keyword in &call.arguments.keywords {
            self.expr(&keyword.value);
        }
    }

    // Branches

    fn if_stmt(&mut self, node: &If<'a>, as_elif: bool) {
        if as_elif {
            self.scorer.fundamental(1);
        } else {
            self.scorer.structural();
        }
        self.scorer.decision(1);
        self.expr(node.test);
        self.nested_body(node.body);
        match or_else(node.clauses) {
            OrElse::Empty => {}
            OrElse::If(elif) if self.lines.is_elif(elif.start) => self.if_stmt(&elif, true),
            OrElse::If(inner) => {
                self.scorer.fundamental(1);
                let region = self.scorer.enter_nesting();
                self.if_stmt(&inner, false);
                self.scorer.leave_nesting(region);
            }
            OrElse::Body(body) => {
                self.scorer.fundamental(1);
                self.nested_body(body);
            }
        }
    }

    fn if_exp(&mut self, node: &'a ExprIf) {
        self.scorer.structural();
        self.scorer.decision(1);
        self.expr(&node.test);
        let region = self.scorer.enter_nesting();
        self.expr(&node.body);
        self.expr(&node.orelse);
        self.scorer.leave_nesting(region);
    }

    fn loop_stmt(&mut self, header: &[&'a Expr], body: &'a [Stmt], orelse: &'a [Stmt]) {
        self.scorer.structural();
        self.scorer.decision(1);
        for expression in header {
            self.expr(expression);
        }
        self.nested_body(body);
        if !orelse.is_empty() {
            self.scorer.fundamental(1);
            self.nested_body(orelse);
        }
    }

    fn try_stmt(&mut self, node: &'a StmtTry) {
        self.body(&node.body);
        for handler in &node.handlers {
            let ExceptHandler::ExceptHandler(handler) = handler;
            self.scorer.structural();
            self.scorer.decision(1);
            self.optional(handler.type_.as_deref());
            self.nested_body(&handler.body);
        }
        self.body(&node.orelse);
        self.body(&node.finalbody);
    }

    /// Patterns are not walked. A bare capture (`case x:`) counts as a wildcard, as `case _:` does.
    fn match_stmt(&mut self, node: &'a StmtMatch) {
        self.scorer.structural();
        self.expr(&node.subject);
        for case in &node.cases {
            let capture =
                matches!(&case.pattern, Pattern::MatchAs(capture) if capture.pattern.is_none());
            if !capture || case.guard.is_some() {
                self.scorer.decision(1);
            }
            if let Some(guard) = &case.guard {
                self.scorer.fundamental(1);
                self.scorer.decision(1);
                self.expr(guard);
            }
            self.nested_body(&case.body);
        }
    }

    // Expressions

    /// A boolean chain's operator runs count once, at its outermost `BoolOp`.
    fn bool_op(&mut self, node: &'a ExprBoolOp, flattened: bool) {
        if !flattened {
            let mut operators = Vec::new();
            flatten(node, &mut operators);
            self.scorer.fundamental(operator_runs(&operators));
        }
        self.scorer.decision(node.values.len() - 1);
        for value in &node.values {
            match value {
                Expr::BoolOp(inner) => self.bool_op(inner, true),
                _ => self.expr(value),
            }
        }
    }

    fn comprehension(&mut self, heads: &[&'a Expr], generators: &'a [Comprehension]) {
        for (index, generator) in generators.iter().enumerate() {
            let ifs = generator.ifs.len();
            self.scorer.decision(1 + ifs);
            self.scorer.fundamental(usize::from(index > 0) + ifs);
        }
        for head in heads {
            self.expr(head);
        }
        for generator in generators {
            self.expr(&generator.target);
            self.expr(&generator.iter);
            self.exprs(&generator.ifs);
        }
    }

    fn interpolations(&mut self, elements: &'a InterpolatedStringElements) {
        for interpolation in elements.interpolations() {
            self.expr(&interpolation.expression);
            if let Some(spec) = &interpolation.format_spec {
                self.interpolations(&spec.elements);
            }
        }
    }

    fn expr(&mut self, expression: &'a Expr) {
        match expression {
            Expr::BoolOp(node) => self.bool_op(node, false),
            Expr::Lambda(node) => self.lambda(node),
            Expr::If(node) => self.if_exp(node),
            Expr::Call(node) => self.call(node),
            Expr::ListComp(node) => self.comprehension(&[&node.elt], &node.generators),
            Expr::SetComp(node) => self.comprehension(&[&node.elt], &node.generators),
            Expr::Generator(node) => self.comprehension(&[&node.elt], &node.generators),
            Expr::DictComp(node) => match node.key.as_deref() {
                Some(key) => self.comprehension(&[key, &node.value], &node.generators),
                None => self.comprehension(&[&node.value], &node.generators),
            },
            _ => self.expr_children(expression),
        }
    }

    /// `ast.iter_child_nodes` for the expressions the reference has no visitor for.
    fn expr_children(&mut self, expression: &'a Expr) {
        match expression {
            Expr::Named(node) => {
                self.expr(&node.target);
                self.expr(&node.value);
            }
            Expr::BinOp(node) => {
                self.expr(&node.left);
                self.expr(&node.right);
            }
            Expr::UnaryOp(node) => self.expr(&node.operand),
            Expr::Dict(node) => {
                for item in &node.items {
                    self.optional(item.key.as_ref());
                }
                for item in &node.items {
                    self.expr(&item.value);
                }
            }
            Expr::Set(node) => self.exprs(&node.elts),
            Expr::List(node) => self.exprs(&node.elts),
            Expr::Tuple(node) => self.exprs(&node.elts),
            Expr::Compare(node) => self.exprs(&node.operands),
            Expr::Await(node) => self.expr(&node.value),
            Expr::Yield(node) => self.optional(node.value.as_deref()),
            Expr::YieldFrom(node) => self.expr(&node.value),
            Expr::Attribute(node) => self.expr(&node.value),
            Expr::Starred(node) => self.expr(&node.value),
            Expr::Subscript(node) => {
                self.expr(&node.value);
                self.expr(&node.slice);
            }
            Expr::Slice(node) => {
                self.optional(node.lower.as_deref());
                self.optional(node.upper.as_deref());
                self.optional(node.step.as_deref());
            }
            Expr::FString(node) => {
                for string in node.value.f_strings() {
                    self.interpolations(&string.elements);
                }
            }
            Expr::TString(node) => {
                for string in node.value.iter() {
                    self.interpolations(&string.elements);
                }
            }
            _ => {}
        }
    }
}

fn or_else(clauses: &[ElifElseClause]) -> OrElse<'_> {
    let Some((first, rest)) = clauses.split_first() else {
        return OrElse::Empty;
    };
    if let Some(test) = &first.test {
        return OrElse::If(If {
            start: first.start(),
            test,
            body: &first.body,
            clauses: rest,
        });
    }
    match &first.body[..] {
        [Stmt::If(node)] => OrElse::If(If {
            start: node.start(),
            test: &node.test,
            body: &node.body,
            clauses: &node.elif_else_clauses,
        }),
        body => OrElse::Body(body),
    }
}

fn flatten(node: &ExprBoolOp, operators: &mut Vec<BoolOp>) {
    for (index, value) in node.values.iter().enumerate() {
        if index > 0 {
            operators.push(node.op);
        }
        if let Expr::BoolOp(inner) = value {
            flatten(inner, operators);
        }
    }
}
