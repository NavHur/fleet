//! Syntax errors: the files `PhpToken::tokenize($source, TOKEN_PARSE)` rejects with a ParseError, which the
//! analyzer reports instead of scoring. mago's parser decides.

use mago_allocator::LocalArena;
use mago_database::file::FileId;
use mago_span::{HasSpan, Span};

use mago_syntax::parser::parse_file_content_with_settings;
use mago_syntax::settings::{LexerSettings, ParserSettings};

/// Fail with mago's first syntax error in `source`, and its line.
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
    match program.errors.first() {
        Some(error) => Err(format!(
            "ParseError: {error} on line {}",
            line_of(source, error.span())
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
