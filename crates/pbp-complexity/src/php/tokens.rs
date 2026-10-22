//! The token stream `PhpToken::tokenize($source, TOKEN_PARSE)` yields, from mago's lexer.
//!
//! Whitespace, comments, and open tags are dropped, as the parser drops them. mago's lexer is context-free
//! where PHP's TOKEN_PARSE is not, so this module restores PHP's view: a keyword used as a name (`->list`,
//! `Foo::class`, `function print()`, `const DEFAULT = 1`, `case Default;`, `f(array: 1)`) is a T_STRING,
//! `enum` and `readonly` are keywords only where PHP's lexer says so, `yield from` is one token, `&` says
//! whether a variable follows, a `{` that opens string interpolation is T_CURLY_OPEN, and `?>` swallows the
//! newline after it.

use mago_database::file::FileId;
use mago_syntax::lexer::Lexer;
use mago_syntax::settings::LexerSettings;
use mago_syntax::token::TokenKind as K;
use mago_syntax_core::input::Input;

use super::heredoc::Document;
use super::names::name;

/// One token as the parser reads it: PHP's token name, its text, and the line it starts on.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Token<'s> {
    pub kind: &'static str,
    pub text: &'s str,
    pub line: usize,
}

struct Raw<'s> {
    kind: K,
    text: &'s str,
    offset: usize,
}

/// Where a brace sits: inside a string's literal text, or inside code (interpolated or not).
#[derive(Clone, Copy, PartialEq, Eq)]
enum Scope {
    Quote(K),
    Brace,
}

/// Tokenize `source`, or fail with mago's lexer error or a heredoc indented less than its marker.
pub fn tokenize(source: &str) -> Result<Vec<Token<'_>>, String> {
    let raw = lex(source)?;
    let significant: Vec<usize> = (0..raw.len())
        .filter(|&index| name(raw[index].kind).is_some())
        .collect();
    let mut stream = Stream {
        source,
        raw: &raw,
        significant: &significant,
        lines: line_starts(source),
        scopes: Vec::new(),
        tokens: Vec::with_capacity(significant.len()),
    };
    let mut position = 0;
    while position < significant.len() {
        position += stream.emit(position);
    }
    Ok(stream.tokens)
}

fn lex(source: &str) -> Result<Vec<Raw<'_>>, String> {
    let settings = LexerSettings {
        enable_short_tags: false,
    };
    let mut lexer = Lexer::new(Input::new(FileId::zero(), source.as_bytes()), settings);
    let mut raw = Vec::new();
    let mut documents: Vec<Document> = Vec::new();
    while let Some(token) = lexer.advance() {
        let token = token.map_err(|error| format!("ParseError: {error}"))?;
        let offset = token.start.offset as usize;
        let text = source.get(offset..offset + token.value.len()).unwrap_or("");
        match token.kind {
            K::DocumentStart(_) => documents.push(Document::new(offset + text.len())),
            K::DocumentEnd => {
                if let Some(document) = documents.pop() {
                    document.check(source, offset, text)?;
                }
            }
            kind => {
                if let Some(document) = documents.last_mut() {
                    document.see(kind, offset);
                }
            }
        }
        raw.push(Raw {
            kind: token.kind,
            text,
            offset,
        });
    }
    Ok(raw)
}

/// Offsets where lines start; PHP ends a line at `\n`, `\r\n`, or a lone `\r`.
fn line_starts(source: &str) -> Vec<usize> {
    let bytes = source.as_bytes();
    let mut starts = vec![0];
    for (index, &byte) in bytes.iter().enumerate() {
        let lone_return = byte == b'\r' && bytes.get(index + 1) != Some(&b'\n');
        if byte == b'\n' || lone_return {
            starts.push(index + 1);
        }
    }
    starts
}

struct Stream<'s, 'r> {
    source: &'s str,
    raw: &'r [Raw<'s>],
    significant: &'r [usize],
    lines: Vec<usize>,
    scopes: Vec<Scope>,
    tokens: Vec<Token<'s>>,
}

impl<'s> Stream<'s, '_> {
    /// Emit the token at significant `position`; returns how many significant tokens it used.
    fn emit(&mut self, position: usize) -> usize {
        let index = self.significant[position];
        let raw = &self.raw[index];
        if raw.kind == K::Yield
            && let Some(from) = self.yield_from(position)
        {
            let end = from.offset + from.text.len();
            let offset = raw.offset;
            self.push("T_YIELD_FROM", &self.source[offset..end], offset);
            return 2;
        }
        if raw.kind == K::InlineText && index > 0 && self.raw[index - 1].kind == K::CloseTag {
            let text = strip_newline(raw.text);
            if !text.is_empty() {
                self.push(
                    "T_INLINE_HTML",
                    text,
                    raw.offset + raw.text.len() - text.len(),
                );
            }
            return 1;
        }
        if raw.kind == K::DollarLeftBrace && !self.in_quote() {
            let (dollar, brace) = raw.text.split_at(1);
            self.push("$", dollar, raw.offset);
            let kind = self.scoped(K::LeftBrace).unwrap_or("{");
            self.push(kind, brace, raw.offset + 1);
            return 1;
        }
        let kind = self.kind(position);
        self.push(kind, raw.text, raw.offset);
        1
    }

    fn push(&mut self, kind: &'static str, text: &'s str, offset: usize) {
        let line = self.lines.partition_point(|&start| start <= offset);
        self.tokens.push(Token { kind, text, line });
    }

    fn raw_at(&self, position: Option<usize>) -> Option<&Raw<'s>> {
        position
            .and_then(|position| self.significant.get(position))
            .map(|&index| &self.raw[index])
    }

    fn kind_at(&self, position: Option<usize>) -> Option<K> {
        self.raw_at(position).map(|raw| raw.kind)
    }

    /// `yield from` with only whitespace or comments between.
    fn yield_from(&self, position: usize) -> Option<&Raw<'s>> {
        let from = self.raw_at(Some(position + 1))?;
        (from.kind == K::From).then_some(from)
    }

    fn kind(&mut self, position: usize) -> &'static str {
        let raw = &self.raw[self.significant[position]];
        let kind = raw.kind;
        if let Some(scoped) = self.scoped(kind) {
            return scoped;
        }
        if (kind.is_keyword() || kind == K::Callable) && self.used_as_name(position) {
            return "T_STRING";
        }
        match kind {
            K::Ampersand if followed_by_variable(&self.source[raw.offset + 1..]) => {
                "T_AMPERSAND_FOLLOWED_BY_VAR_OR_VARARG"
            }
            K::Enum if !self.enum_follows(position) => "T_STRING",
            K::Readonly if self.call_follows(self.significant[position]) => "T_STRING",
            K::QualifiedIdentifier if is_relative(raw.text) => "T_NAME_RELATIVE",
            K::LiteralInteger if overflows(raw.text) => "T_DNUMBER",
            _ => name(kind).unwrap_or("T_STRING"),
        }
    }

    /// Strings and the braces in and around them, tracked so `{` in a string reads as T_CURLY_OPEN.
    fn in_quote(&self) -> bool {
        matches!(self.scopes.last(), Some(Scope::Quote(_)))
    }

    fn scoped(&mut self, kind: K) -> Option<&'static str> {
        let top = self.scopes.last().copied();
        let in_quote = self.in_quote();
        match kind {
            K::DoubleQuote | K::Backtick if top == Some(Scope::Quote(kind)) => {
                self.scopes.pop();
            }
            K::DoubleQuote | K::Backtick | K::DocumentStart(_) => {
                self.scopes.push(Scope::Quote(kind))
            }
            K::DocumentEnd => {
                self.scopes.pop();
            }
            K::LeftBrace if in_quote => {
                self.scopes.push(Scope::Brace);
                return Some("T_CURLY_OPEN");
            }
            K::LeftBrace | K::DollarLeftBrace if !self.scopes.is_empty() => {
                self.scopes.push(Scope::Brace);
            }
            K::RightBrace if top == Some(Scope::Brace) => {
                self.scopes.pop();
            }
            _ => {}
        }
        None
    }

    /// A keyword TOKEN_PARSE reports as T_STRING because the grammar reads it as a name.
    fn used_as_name(&self, position: usize) -> bool {
        let before = position.checked_sub(1);
        let previous = self.kind_at(before);
        let next = self.kind_at(Some(position + 1));
        let kind = self.raw[self.significant[position]].kind;
        match previous {
            Some(
                K::MinusGreaterThan | K::QuestionMinusGreaterThan | K::ColonColon | K::Function,
            ) => true,
            Some(K::Ampersand) => {
                self.kind_at(before.and_then(|b| b.checked_sub(1))) == Some(K::Function)
            }
            Some(K::Case) => matches!(next, Some(K::Semicolon | K::Equal)),
            Some(K::LeftParenthesis | K::Comma) if next == Some(K::Colon) => true,
            // Trait adaptations name methods, `{ exit as quit; quit as exit; }`, but keep modifiers:
            // `quit as public;`.
            Some(K::As) if next == Some(K::Semicolon) => !is_modifier(kind),
            Some(K::LeftBrace | K::Semicolon) if next == Some(K::As) => true,
            _ => next == Some(K::Equal),
        }
    }

    /// PHP's lexer reads `enum` as a keyword only before a name other than `extends` or `implements`.
    fn enum_follows(&self, position: usize) -> bool {
        let Some(next) = self.raw_at(Some(position + 1)) else {
            return false;
        };
        let starts_name = next.text.bytes().next().is_some_and(is_label_start);
        starts_name && !matches!(next.kind, K::Extends | K::Implements)
    }

    /// `readonly` directly before `(`, whitespace aside, is a function name.
    fn call_follows(&self, index: usize) -> bool {
        let mut rest = self.raw[index + 1..].iter();
        let next = match rest.next() {
            Some(raw) if raw.kind == K::Whitespace => rest.next(),
            other => other,
        };
        next.is_some_and(|raw| raw.kind == K::LeftParenthesis)
    }
}

fn is_modifier(kind: K) -> bool {
    matches!(
        kind,
        K::Public | K::Protected | K::Private | K::Static | K::Abstract | K::Final | K::Readonly
    )
}

fn strip_newline(text: &str) -> &str {
    text.strip_prefix("\r\n")
        .or_else(|| text.strip_prefix('\n'))
        .or_else(|| text.strip_prefix('\r'))
        .unwrap_or(text)
}

fn is_label_start(byte: u8) -> bool {
    byte.is_ascii_alphabetic() || byte == b'_' || byte >= 0x80
}

fn followed_by_variable(rest: &str) -> bool {
    let rest = rest.trim_start_matches([' ', '\t', '\r', '\n']);
    rest.starts_with('$') || rest.starts_with("...")
}

fn is_relative(name: &str) -> bool {
    name.get(..10)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case("namespace\\"))
}

/// An integer literal past PHP_INT_MAX, which PHP lexes as a float.
fn overflows(text: &str) -> bool {
    let digits: String = text.chars().filter(|&c| c != '_').collect();
    let lower = digits.to_ascii_lowercase();
    let (body, radix) = match lower.get(..2) {
        Some("0x") => (&lower[2..], 16),
        Some("0b") => (&lower[2..], 2),
        Some("0o") => (&lower[2..], 8),
        _ if lower.len() > 1 && lower.starts_with('0') => (&lower[1..], 8),
        _ => (lower.as_str(), 10),
    };
    i64::from_str_radix(body, radix).is_err()
}
