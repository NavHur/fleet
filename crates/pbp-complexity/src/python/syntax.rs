//! Parse a module, rejecting exactly what CPython 3.15's `ast.parse` rejects.
//!
//! ruff's parser covers the grammar. `ast.parse` also refuses a few things ruff leaves to its semantic
//! checks or never sees: null bytes, a byte order mark kept in the text (the Python analyzer read with
//! `utf-8`, not `utf-8-sig`), indentation that mixes tabs and spaces inconsistently, unknown features in
//! the leading `__future__` block, `lazy from __future__`, and `!=` once `barry_as_FLUFL` is imported.

use ruff_python_ast::statement_visitor::{StatementVisitor, walk_stmt};
use ruff_python_ast::token::{TokenKind, Tokens};
use ruff_python_ast::{Expr, ModModule, PythonVersion, Stmt, StmtImportFrom};
use ruff_python_parser::{Mode, ParseOptions, Parsed, parse_unchecked};
use ruff_text_size::{Ranged, TextSize};

/// `__future__.all_feature_names` in CPython 3.15.
const FUTURE_FEATURES: [&str; 10] = [
    "nested_scopes",
    "generators",
    "division",
    "absolute_import",
    "with_statement",
    "print_function",
    "unicode_literals",
    "barry_as_FLUFL",
    "generator_stop",
    "annotations",
];

pub fn parse(source: &str) -> Result<Parsed<ModModule>, String> {
    if source.contains('\0') {
        return Err("SyntaxError: source code string cannot contain null bytes".to_owned());
    }
    if source.starts_with('\u{feff}') {
        return Err("SyntaxError: invalid non-printable character U+FEFF".to_owned());
    }
    let options = ParseOptions::from(Mode::Module).with_target_version(PythonVersion::PY315);
    let parsed = parse_unchecked(source, options)
        .try_into_module()
        .expect("module mode parses a module");
    if let Some(error) = parsed.errors().first() {
        return Err(format!("SyntaxError: {}", error.error));
    }
    if let Some(error) = parsed.unsupported_syntax_errors().first() {
        return Err(format!("SyntaxError: {error}"));
    }
    if !consistent_tabs(source, parsed.tokens()) {
        return Err("TabError: inconsistent use of tabs and spaces in indentation".to_owned());
    }
    let features = future_features(parsed.suite())?;
    if features.contains(&"barry_as_FLUFL") && has_not_equal(&parsed) {
        return Err("SyntaxError: with Barry as BDFL, use '<>' instead of '!='".to_owned());
    }
    let mut lazy = LazyFuture(false);
    lazy.visit_body(parsed.suite());
    if lazy.0 {
        return Err("SyntaxError: lazy from __future__ import is not allowed".to_owned());
    }
    Ok(parsed)
}

fn is_future_import(statement: &Stmt) -> Option<&StmtImportFrom> {
    let Stmt::ImportFrom(import) = statement else {
        return None;
    };
    let future = import.level == 0 && import.module.as_ref().is_some_and(|m| m == "__future__");
    future.then_some(import)
}

fn is_docstring(statement: &Stmt) -> bool {
    matches!(statement, Stmt::Expr(node) if matches!(*node.value, Expr::StringLiteral(_)))
}

/// The features the leading `__future__` block imports: after an optional docstring, the `from __future__`
/// imports up to the first other statement. CPython checks only these; a later one is the compiler's to
/// reject.
fn future_features(body: &[Stmt]) -> Result<Vec<&str>, String> {
    let skip = usize::from(body.first().is_some_and(is_docstring));
    let mut features = Vec::new();
    for import in body[skip..].iter().map_while(is_future_import) {
        for alias in &import.names {
            let name = alias.name.as_str();
            if name == "braces" {
                return Err("SyntaxError: not a chance".to_owned());
            }
            if !FUTURE_FEATURES.contains(&name) {
                return Err(format!("SyntaxError: future feature {name} is not defined"));
            }
            features.push(name);
        }
    }
    Ok(features)
}

fn has_not_equal(parsed: &Parsed<ModModule>) -> bool {
    parsed
        .tokens()
        .iter()
        .any(|token| token.kind() == TokenKind::NotEqual)
}

/// Finds a `lazy from __future__ import` at any depth.
struct LazyFuture(bool);

impl<'a> StatementVisitor<'a> for LazyFuture {
    fn visit_stmt(&mut self, statement: &'a Stmt) {
        if let Stmt::ImportFrom(import) = statement {
            self.0 |= import.is_lazy && is_future_import(statement).is_some();
        }
        walk_stmt(self, statement);
    }
}

/// An indentation measured CPython's two ways: tabs to the next multiple of 8, and tabs as one column.
#[derive(Clone, Copy, PartialEq, Eq)]
struct Indent {
    column: usize,
    alternate: usize,
}

const TAB_SIZE: usize = 8;

fn indent_before(source: &str, offset: TextSize) -> Indent {
    let before = &source[..offset.to_usize()];
    let line = &before[before.rfind('\n').map_or(0, |index| index + 1)..];
    let mut indent = Indent {
        column: 0,
        alternate: 0,
    };
    for character in line.chars() {
        indent = match character {
            '\t' => Indent {
                column: (indent.column / TAB_SIZE + 1) * TAB_SIZE,
                alternate: indent.alternate + 1,
            },
            '\x0c' => Indent {
                column: 0,
                alternate: 0,
            },
            _ => Indent {
                column: indent.column + 1,
                alternate: indent.alternate + 1,
            },
        };
    }
    indent
}

/// CPython's tokenizer TabError: at each logical line, the two measures must order the line against the
/// enclosing indentation levels the same way. ruff compares columns only.
fn consistent_tabs(source: &str, tokens: &Tokens) -> bool {
    let mut levels = vec![Indent {
        column: 0,
        alternate: 0,
    }];
    let mut at_line_start = true;
    for token in tokens.iter() {
        match token.kind() {
            TokenKind::Newline => at_line_start = true,
            TokenKind::NonLogicalNewline
            | TokenKind::Comment
            | TokenKind::Indent
            | TokenKind::Dedent
            | TokenKind::EndOfFile => {}
            _ if at_line_start => {
                at_line_start = false;
                if !indent_fits(&mut levels, indent_before(source, token.start())) {
                    return false;
                }
            }
            _ => {}
        }
    }
    true
}

/// Push, keep, or pop `levels` for a line's indent; false when the two measures disagree.
fn indent_fits(levels: &mut Vec<Indent>, indent: Indent) -> bool {
    let top = *levels.last().expect("the base level stays");
    if indent.column > top.column {
        levels.push(indent);
        return indent.alternate > top.alternate;
    }
    while levels.len() > 1 && indent.column < levels[levels.len() - 1].column {
        levels.pop();
    }
    levels
        .last()
        .is_some_and(|level| level.alternate == indent.alternate)
}
