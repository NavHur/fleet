//! Syntax errors: the files `PhpToken::tokenize($source, TOKEN_PARSE)` rejects with a ParseError, which the
//! analyzer reports instead of scoring. mago's parser decides, and grammar.rs adds the rules it leaves to later
//! analysis.

use mago_allocator::LocalArena;
use mago_database::file::FileId;
use mago_span::{HasSpan, Span};

use super::grammar::first_violation;
use mago_syntax::parser::parse_file_content_with_settings;
use mago_syntax::settings::{LexerSettings, ParserSettings};

/// Fail with the first syntax error in `source`, mago's or one PHP's grammar adds (grammar.rs), and its line.
pub fn check(source: &str) -> Result<(), String> {
    let arena = LocalArena::new();
    let settings = ParserSettings {
        lexer: LexerSettings {
            enable_short_tags: false,
        },
        ..ParserSettings::default()
    };
    let program =
        parse_file_content_with_settings(&arena, FileId::zero(), source.as_bytes(), settings);
    if let Some(error) = program.errors.first() {
        return Err(format!(
            "ParseError: {error} on line {}",
            line_of(source, error.span())
        ));
    }
    match first_violation(program) {
        Some(span) => Err(format!(
            "ParseError: syntax error, unexpected token on line {}",
            line_of(source, span)
        )),
        None => Ok(()),
    }
}

fn line_of(source: &str, span: Span) -> usize {
    let offset = (span.start.offset as usize).min(source.len());
    1 + source.as_bytes()[..offset]
        .iter()
        .filter(|&&byte| byte == b'\n')
        .count()
}
