//! Grammar rules PHP's parser enforces and mago's leaves to later analysis: what may be assigned to,
//! iterated into, or instantiated, and which modifiers a declaration may carry (modifiers.rs).
//! `'key' = $value`, `foreach ($a as $k > $v)`, `new 'Name'`, `[& 'str']`, `unset(f)`, `[readonly]`,
//! `f(static)`, `function if()`, `namespace;`, `static class`, and `readonly function` parse in mago but not in PHP, so TOKEN_PARSE rejects the file.

use mago_span::{HasSpan, Span};
use mago_syntax::cst::Program;
use mago_syntax::cst::cst::Statement;
use mago_syntax::cst::cst::{
    Access, AnonymousClass, Assignment, AssignmentOperator, Binary, BinaryOperator, Class,
    ClassConstantAccess, ClassLikeConstant, ConstantAccess, Expression, ForeachTarget, Function,
    FunctionLikeParameter, HookedProperty, Identifier, Instantiation, Keyword, Label, Method,
    Namespace, NamespaceBody, PlainProperty, StaticMethodCall, StaticMethodPartialApplication,
    StaticPropertyAccess, UnaryPrefix, UnaryPrefixOperator, Unset,
};
use mago_syntax::walker::Walker;

use super::modifiers::{Target, invalid};

/// The first expression or declaration in `program` that PHP's grammar refuses.
pub fn first_violation(program: &Program) -> Option<Span> {
    let mut found = Found::default();
    Rules.walk_program(program, &mut found);
    found
        .violations
        .into_iter()
        .min_by_key(|span| span.start.offset)
}

/// Keywords PHP's lexer never reads as a constant, function, or label name; `enum` is absent because it is one outside
/// a declaration.
const RESERVED: &[&str] = &[
    "abstract",
    "array",
    "as",
    "break",
    "callable",
    "case",
    "catch",
    "class",
    "clone",
    "const",
    "continue",
    "declare",
    "default",
    "do",
    "echo",
    "else",
    "elseif",
    "empty",
    "enddeclare",
    "endfor",
    "endforeach",
    "endif",
    "endswitch",
    "endwhile",
    "eval",
    "exit",
    "die",
    "extends",
    "final",
    "finally",
    "fn",
    "for",
    "foreach",
    "function",
    "global",
    "goto",
    "if",
    "implements",
    "include",
    "include_once",
    "instanceof",
    "insteadof",
    "interface",
    "isset",
    "list",
    "match",
    "namespace",
    "new",
    "or",
    "and",
    "xor",
    "print",
    "private",
    "protected",
    "public",
    "readonly",
    "require",
    "require_once",
    "return",
    "static",
    "switch",
    "throw",
    "trait",
    "try",
    "unset",
    "use",
    "var",
    "while",
    "yield",
];

/// The walk's findings, where a bare `static` names a class (`new static`, `static::x`), the only
/// places PHP's grammar takes it as an expression, and the namespaces declared at the top level, the
/// only place one may be declared.
#[derive(Default)]
struct Found {
    violations: Vec<Span>,
    class_positions: Vec<Span>,
    top_namespaces: Vec<Span>,
}

struct Rules;

impl<'ast, 'arena> Walker<'ast, 'arena, Found> for Rules {
    fn walk_in_program(&self, program: &'ast Program<'arena>, found: &mut Found) {
        for statement in program.statements.iter() {
            if let Statement::Namespace(namespace) = statement {
                found.top_namespaces.push(namespace.span());
            }
        }
    }

    fn walk_in_class(&self, class: &'ast Class<'arena>, found: &mut Found) {
        refuse(
            invalid(&class.modifiers, Target::Class),
            class.span(),
            &mut found.violations,
        );
    }

    fn walk_in_anonymous_class(&self, class: &'ast AnonymousClass<'arena>, found: &mut Found) {
        refuse(
            invalid(&class.modifiers, Target::AnonymousClass),
            class.span(),
            &mut found.violations,
        );
    }

    fn walk_in_method(&self, method: &'ast Method<'arena>, found: &mut Found) {
        refuse(
            invalid(&method.modifiers, Target::Method),
            method.span(),
            &mut found.violations,
        );
    }

    fn walk_in_class_like_constant(
        &self,
        constant: &'ast ClassLikeConstant<'arena>,
        found: &mut Found,
    ) {
        refuse(
            invalid(&constant.modifiers, Target::Constant),
            constant.span(),
            &mut found.violations,
        );
    }

    fn walk_in_plain_property(&self, property: &'ast PlainProperty<'arena>, found: &mut Found) {
        refuse(
            invalid(&property.modifiers, Target::Property),
            property.span(),
            &mut found.violations,
        );
    }

    fn walk_in_hooked_property(&self, property: &'ast HookedProperty<'arena>, found: &mut Found) {
        refuse(
            invalid(&property.modifiers, Target::Property),
            property.span(),
            &mut found.violations,
        );
    }

    fn walk_in_function_like_parameter(
        &self,
        parameter: &'ast FunctionLikeParameter<'arena>,
        found: &mut Found,
    ) {
        refuse(
            invalid(&parameter.modifiers, Target::Parameter),
            parameter.span(),
            &mut found.violations,
        );
    }

    fn walk_in_assignment(&self, assignment: &'ast Assignment<'arena>, found: &mut Found) {
        let destructures = matches!(assignment.lhs, Expression::List(_) | Expression::Array(_));
        let plain = matches!(assignment.operator, AssignmentOperator::Assign(_));
        if !(is_variable(assignment.lhs) || plain && destructures) {
            found.violations.push(assignment.lhs.span());
        }
    }

    fn walk_in_foreach_target(&self, target: &'ast ForeachTarget<'arena>, found: &mut Found) {
        let (key, value) = match target {
            ForeachTarget::Value(target) => (None, target.value),
            ForeachTarget::KeyValue(target) => (Some(target.key), target.value),
        };
        for expression in key.into_iter().chain([value]) {
            if !is_foreach_variable(expression) {
                found.violations.push(expression.span());
            }
        }
    }

    fn walk_in_instantiation(&self, instantiation: &'ast Instantiation<'arena>, found: &mut Found) {
        found.class_positions.push(instantiation.class.span());
        if !is_class_reference(instantiation.class) {
            found.violations.push(instantiation.class.span());
        }
    }

    fn walk_in_binary(&self, binary: &'ast Binary<'arena>, found: &mut Found) {
        if matches!(binary.operator, BinaryOperator::Instanceof(_)) {
            found.class_positions.push(binary.rhs.span());
        }
    }

    fn walk_in_static_method_call(&self, call: &'ast StaticMethodCall<'arena>, found: &mut Found) {
        found.class_positions.push(call.class.span());
    }

    fn walk_in_static_method_partial_application(
        &self,
        application: &'ast StaticMethodPartialApplication<'arena>,
        found: &mut Found,
    ) {
        found.class_positions.push(application.class.span());
    }

    fn walk_in_static_property_access(
        &self,
        access: &'ast StaticPropertyAccess<'arena>,
        found: &mut Found,
    ) {
        found.class_positions.push(access.class.span());
    }

    fn walk_in_class_constant_access(
        &self,
        access: &'ast ClassConstantAccess<'arena>,
        found: &mut Found,
    ) {
        found.class_positions.push(access.class.span());
    }

    fn walk_in_static_keyword(&self, keyword: &'ast Keyword<'arena>, found: &mut Found) {
        refuse(
            !found.class_positions.contains(&keyword.span()),
            keyword.span(),
            &mut found.violations,
        );
    }

    fn walk_in_unary_prefix(&self, prefix: &'ast UnaryPrefix<'arena>, found: &mut Found) {
        let reference = matches!(prefix.operator, UnaryPrefixOperator::Reference(_));
        refuse(
            reference && !is_variable(prefix.operand),
            prefix.span(),
            &mut found.violations,
        );
    }

    fn walk_in_unset(&self, unset: &'ast Unset<'arena>, found: &mut Found) {
        for value in &unset.values {
            refuse(!is_variable(value), value.span(), &mut found.violations);
        }
    }

    fn walk_in_constant_access(&self, constant: &'ast ConstantAccess<'arena>, found: &mut Found) {
        let reserved = matches!(&constant.name, Identifier::Local(name) if is_reserved(name.value));
        refuse(reserved, constant.span(), &mut found.violations);
    }

    /// `function readonly()` is the one reserved name PHP's lexer lets a function take.
    fn walk_in_function(&self, function: &'ast Function<'arena>, found: &mut Found) {
        let name = function.name.value;
        let reserved = is_reserved(name) && !name.eq_ignore_ascii_case(b"readonly");
        refuse(reserved, function.name.span(), &mut found.violations);
    }

    fn walk_in_label(&self, label: &'ast Label<'arena>, found: &mut Found) {
        refuse(
            is_reserved(label.name.value),
            label.span(),
            &mut found.violations,
        );
    }

    /// `namespace;` or `if ($a) namespace A;`: only a braced namespace may go unnamed, and none may
    /// nest.
    fn walk_in_namespace(&self, namespace: &'ast Namespace<'arena>, found: &mut Found) {
        let unnamed = namespace.name.is_none();
        let implicit = matches!(namespace.body, NamespaceBody::Implicit(_));
        let nested = !found.top_namespaces.contains(&namespace.span());
        refuse(
            unnamed && implicit || nested,
            namespace.span(),
            &mut found.violations,
        );
    }
}

fn is_reserved(name: &[u8]) -> bool {
    RESERVED
        .iter()
        .any(|keyword| keyword.as_bytes().eq_ignore_ascii_case(name))
}

fn refuse(refused: bool, span: Span, violations: &mut Vec<Span>) {
    if refused {
        violations.push(span);
    }
}

/// PHP's `variable` production: what an assignment may write to. Calls and nullsafe accesses parse here
/// and fail only at compile time, which TOKEN_PARSE never reaches.
fn is_variable(expression: &Expression) -> bool {
    match expression {
        Expression::Variable(_)
        | Expression::ArrayAccess(_)
        | Expression::ArrayAppend(_)
        | Expression::Call(_)
        | Expression::PartialApplication(_) => true,
        Expression::Access(access) => !matches!(access, Access::ClassConstant(_)),
        _ => false,
    }
}

/// A foreach key or value: a variable, a destructuring list, or a reference to a variable.
fn is_foreach_variable(expression: &Expression) -> bool {
    match expression {
        Expression::List(_) | Expression::Array(_) => true,
        Expression::UnaryPrefix(prefix) => {
            matches!(prefix.operator, UnaryPrefixOperator::Reference(_))
                && is_variable(prefix.operand)
        }
        _ => is_variable(expression),
    }
}

/// What may follow `new`: a class name, `static`/`self`/`parent`, a parenthesized expression, or a
/// variable built only from properties and array offsets.
fn is_class_reference(expression: &Expression) -> bool {
    match expression {
        Expression::Identifier(_)
        | Expression::Static(_)
        | Expression::Self_(_)
        | Expression::Parent(_)
        | Expression::Parenthesized(_) => true,
        _ => is_new_variable(expression),
    }
}

fn is_new_variable(expression: &Expression) -> bool {
    match expression {
        Expression::Variable(_) => true,
        Expression::ArrayAccess(access) => is_new_variable(access.array),
        Expression::Access(Access::Property(access)) => is_new_variable(access.object),
        Expression::Access(Access::NullSafeProperty(access)) => is_new_variable(access.object),
        Expression::Access(Access::StaticProperty(access)) => is_class_reference(access.class),
        _ => false,
    }
}
