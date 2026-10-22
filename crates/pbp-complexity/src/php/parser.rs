//! The token-stream parser: a cursor over the tokens, bracket pairing, and statements.
//!
//! Each method mirrors the matching one in the retired complexity_php.py's `Parser`, so scores stayed
//! identical through the port. Declarations and expressions live in their own modules.

use super::tokens::Token;
use crate::scorer::{Function, Scorer};

pub(super) const EXPRESSION_END: &[&str] = &[";", "T_CLOSE_TAG"];
const CLASSLIKE: &[&str] = &["T_CLASS", "T_INTERFACE", "T_TRAIT", "T_ENUM"];

/// The closer each opener pairs with.
pub(super) fn closer_of(kind: &str) -> Option<&'static str> {
    match kind {
        "(" => Some(")"),
        "[" | "T_ATTRIBUTE" => Some("]"),
        "{" | "T_CURLY_OPEN" | "T_DOLLAR_OPEN_CURLY_BRACES" => Some("}"),
        _ => None,
    }
}

pub(super) struct Parser<'s> {
    pub(super) tokens: Vec<Token<'s>>,
    pub(super) i: usize,
    pub(super) scorer: Scorer,
    pairs: Vec<Option<usize>>,
    /// The error the Python analyzer would have crashed with, if any.
    error: Option<String>,
}

impl<'s> Parser<'s> {
    pub(super) fn new(tokens: Vec<Token<'s>>) -> Self {
        let pairs = pair_brackets(&tokens);
        Parser {
            tokens,
            i: 0,
            scorer: Scorer::default(),
            pairs,
            error: None,
        }
    }

    /// Score every function in the file.
    pub(super) fn run(mut self) -> Result<Vec<Function>, String> {
        while !self.at_end() {
            self.statement_advancing();
        }
        match self.error {
            Some(error) => Err(error),
            None => Ok(self.scorer.functions),
        }
    }

    // Cursor

    pub(super) fn kind(&self, offset: usize) -> &'static str {
        self.tokens
            .get(self.i + offset)
            .map_or("EOF", |token| token.kind)
    }

    pub(super) fn text(&self, offset: usize) -> &'s str {
        self.tokens
            .get(self.i + offset)
            .map_or("", |token| token.text)
    }

    /// The kind of the token before the cursor, or "" at the start.
    pub(super) fn before(&self) -> &'static str {
        match self.i {
            0 => "",
            i => self.tokens.get(i - 1).map_or("", |token| token.kind),
        }
    }

    pub(super) fn line(&self, index: usize) -> usize {
        let last = self.tokens.len().saturating_sub(1);
        self.tokens
            .get(index.min(last))
            .map_or(1, |token| token.line)
    }

    pub(super) fn at_end(&self) -> bool {
        self.i >= self.tokens.len()
    }

    /// The index of the closer paired with the opener at `index`, else `default`.
    pub(super) fn closer(&self, index: usize, default: usize) -> usize {
        self.pairs.get(index).copied().flatten().unwrap_or(default)
    }

    /// Jump past the bracketed group starting at the cursor; return the closer's index.
    pub(super) fn skip_group(&mut self) -> usize {
        let closer = self.closer(self.i, self.tokens.len().wrapping_sub(1));
        self.i = closer.wrapping_add(1);
        closer
    }

    pub(super) fn skip_until(&mut self, kinds: &[&str]) {
        while !self.at_end() && !kinds.contains(&self.kind(0)) {
            if closer_of(self.kind(0)).is_some() {
                self.skip_group();
            } else {
                self.i += 1;
            }
        }
    }

    pub(super) fn expect(&mut self, kind: &str) {
        if self.kind(0) == kind {
            self.i += 1;
        }
    }

    pub(super) fn fail(&mut self, error: String) {
        self.error.get_or_insert(error);
    }

    // Statements

    /// One statement, stepping past the token when nothing consumed it so the walk never stalls.
    pub(super) fn statement_advancing(&mut self) {
        let before = self.i;
        self.statement();
        self.advance_if_stalled(before);
    }

    /// Step past the cursor's token when a loop pass consumed nothing. The Python lacks this in class
    /// bodies and `match` arms and loops forever there, but only on token streams PHP rejects and mago
    /// accepts (`'k' = match > 1`), so it changes no output the Python produces.
    pub(super) fn advance_if_stalled(&mut self, before: usize) {
        if self.i == before {
            self.i += 1;
        }
    }

    pub(super) fn statement(&mut self) {
        match self.kind(0) {
            "T_INLINE_HTML" | "T_CLOSE_TAG" | ";" | "T_ABSTRACT" | "T_FINAL" | "T_READONLY" => {
                self.i += 1
            }
            "T_OPEN_TAG_WITH_ECHO" => {
                self.i += 1;
                self.expression(EXPRESSION_END, None);
                self.expect(";");
            }
            "{" => self.block(),
            "T_ATTRIBUTE" => {
                self.skip_group();
            }
            kind if CLASSLIKE.contains(&kind) => self.class_declaration(None),
            "T_FUNCTION" if self.named_function_follows() => self.function_declaration(None),
            "T_IF" => self.if_statement(),
            "T_WHILE" => self.loop_statement("T_ENDWHILE"),
            "T_FOR" => self.loop_statement("T_ENDFOR"),
            "T_FOREACH" => self.loop_statement("T_ENDFOREACH"),
            "T_DO" => self.do_while(),
            "T_SWITCH" => self.switch(),
            "T_TRY" => self.try_statement(),
            "T_GOTO" => {
                self.scorer.fundamental(1);
                self.skip_until(EXPRESSION_END);
            }
            "T_BREAK" | "T_CONTINUE" => self.jump(),
            "T_NAMESPACE" | "T_USE" | "T_DECLARE" => {
                self.i += 1;
                self.skip_until(&[";", "{", "T_CLOSE_TAG"]);
                if self.kind(0) == "{" {
                    self.block();
                }
            }
            _ => {
                self.expression(EXPRESSION_END, None);
                self.expect(";");
            }
        }
    }

    pub(super) fn block(&mut self) {
        let closer = self.closer(self.i, self.tokens.len());
        self.i += 1;
        while self.i < closer && !self.at_end() {
            self.statement_advancing();
        }
        self.i = closer + 1;
    }

    /// A braced block, an alternative-syntax block, or a single statement.
    pub(super) fn body(&mut self, alternative_ends: &[&str]) {
        match self.kind(0) {
            "{" => self.block(),
            ":" => {
                self.i += 1;
                while !self.at_end() && !alternative_ends.contains(&self.kind(0)) {
                    self.statement_advancing();
                }
            }
            _ => self.statement(),
        }
    }

    pub(super) fn condition(&mut self) {
        if self.kind(0) == "(" {
            let closer = self.closer(self.i, self.tokens.len());
            self.i += 1;
            self.expression(&[")"], Some(closer));
            self.i = closer + 1;
        }
    }
}

fn pair_brackets(tokens: &[Token]) -> Vec<Option<usize>> {
    let mut pairs = vec![None; tokens.len()];
    let mut stack: Vec<(usize, &str)> = Vec::new();
    for (index, token) in tokens.iter().enumerate() {
        if let Some(closer) = closer_of(token.kind) {
            stack.push((index, closer));
        } else if let Some(&(opener, closer)) = stack.last()
            && token.kind == closer
        {
            pairs[opener] = Some(index);
            stack.pop();
        }
    }
    pairs
}
