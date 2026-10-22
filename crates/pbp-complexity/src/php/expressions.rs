//! Expressions: boolean operator runs, shorthand and full ternaries, calls, brackets, and the functions,
//! classes, and `match` expressions nested inside them.

use super::parser::Parser;
use crate::scorer::operator_runs;

const CALLABLE_BEFORE: &[&str] = &[
    "T_STRING",
    "T_VARIABLE",
    "T_NAME_QUALIFIED",
    "T_NAME_FULLY_QUALIFIED",
    "T_NAME_RELATIVE",
    ")",
    "]",
    "}",
    "T_STATIC",
    "T_ARRAY",
    "T_ISSET",
    "T_EMPTY",
    "T_EXIT",
    "T_LIST",
    "T_UNSET",
    "T_EVAL",
    "!",
];

/// The boolean operator a token adds to the chain, if it is one.
fn boolean(kind: &str) -> Option<&'static str> {
    match kind {
        "T_BOOLEAN_AND" | "T_LOGICAL_AND" => Some("and"),
        "T_BOOLEAN_OR" | "T_LOGICAL_OR" => Some("or"),
        "T_LOGICAL_XOR" => Some("xor"),
        _ => None,
    }
}

impl Parser<'_> {
    /// Walk tokens until a stop kind; score ternaries, chains, calls, and nested functions.
    pub(super) fn expression(&mut self, stop: &[&str], limit: Option<usize>) {
        let mut chain = Vec::new();
        self.walk(stop, limit, &mut chain, true);
    }

    /// The expression loop. A grouping parenthesis continues its enclosing `chain` rather than owning one,
    /// so only the owner scores the chain's operator runs.
    fn walk(
        &mut self,
        stop: &[&str],
        limit: Option<usize>,
        chain: &mut Vec<&'static str>,
        own: bool,
    ) {
        while !self.at_end() && limit.is_none_or(|limit| self.i < limit) {
            let kind = self.kind(0);
            if stop.contains(&kind) || matches!(kind, ")" | "]" | "}") {
                break;
            }
            if kind == "?" && self.kind(1) != ":" {
                self.flush(chain, own);
                self.ternary(stop, limit);
                break;
            }
            self.step(kind, stop, limit, chain, own);
        }
        self.flush(chain, own);
    }

    fn flush(&mut self, chain: &mut Vec<&'static str>, own: bool) {
        if own {
            self.scorer.fundamental(operator_runs(chain));
            chain.clear();
        }
    }

    fn step(
        &mut self,
        kind: &str,
        stop: &[&str],
        limit: Option<usize>,
        chain: &mut Vec<&'static str>,
        own: bool,
    ) {
        if let Some(operator) = boolean(kind) {
            chain.push(operator);
            self.scorer.decision(1);
            self.i += 1;
            return;
        }
        match kind {
            // `??`, `??=`, and the short ternary `?:` are cyclomatic decisions, cognitively free.
            "T_COALESCE" | "T_COALESCE_EQUAL" | "?" => {
                self.flush(chain, own);
                self.scorer.decision(1);
                self.i += if kind == "?" { 2 } else { 1 };
            }
            "," | "T_DOUBLE_ARROW" => {
                self.flush(chain, own);
                self.i += 1;
            }
            "(" => self.parenthesis(chain),
            "[" | "T_CURLY_OPEN" | "T_DOLLAR_OPEN_CURLY_BRACES" | "{" => self.brackets(),
            "T_FUNCTION" => self.closure(),
            "T_FN" => self.arrow_function(stop, limit),
            "T_MATCH" => self.match_expression(),
            "T_NEW" if self.kind(1) == "T_CLASS" => {
                self.i += 1;
                self.class_declaration(Some("class@anonymous".to_owned()));
            }
            "T_ATTRIBUTE" => {
                self.skip_group();
            }
            "T_STRING" | "T_NAME_QUALIFIED" | "T_NAME_FULLY_QUALIFIED" if self.kind(1) == "(" => {
                if let Some(form) = self.call_form() {
                    self.scorer.call(&form);
                }
                self.i += 1;
            }
            _ => self.i += 1,
        }
    }

    fn ternary(&mut self, stop: &[&str], limit: Option<usize>) {
        self.scorer.structural();
        self.scorer.decision(1);
        self.i += 1;
        let region = self.scorer.enter_nesting();
        self.expression(&[":"], limit);
        self.expect(":");
        self.expression(stop, limit);
        self.scorer.leave_nesting(region);
    }

    /// Call arguments each start their own expression; grouping parentheses continue the chain.
    fn parenthesis(&mut self, chain: &mut Vec<&'static str>) {
        let closer = self.closer(self.i, self.tokens.len());
        let before = self.before();
        self.i += 1;
        if CALLABLE_BEFORE.contains(&before) {
            self.items(&[","], closer);
        } else {
            self.walk(&[], Some(closer), chain, false);
        }
        self.i = closer + 1;
    }

    fn brackets(&mut self) {
        let closer = self.closer(self.i, self.tokens.len());
        self.i += 1;
        self.items(&[",", "T_DOUBLE_ARROW"], closer);
        self.i = closer + 1;
    }

    /// Separated items up to `closer`, each its own expression.
    fn items(&mut self, separators: &[&str], closer: usize) {
        while self.i < closer {
            self.expression(separators, Some(closer));
            if !separators.contains(&self.kind(0)) {
                break;
            }
            self.i += 1;
        }
    }

    /// The recursion form of a call whose name is at the cursor, if any.
    fn call_form(&self) -> Option<String> {
        let name = self.text(0);
        let owner = || match self.i {
            0 | 1 => "",
            i => self.tokens[i - 2].text,
        };
        match self.before() {
            "T_FUNCTION" | "T_NEW" | "T_FN" => None,
            "T_OBJECT_OPERATOR" | "T_NULLSAFE_OBJECT_OPERATOR" => {
                (owner() == "$this").then(|| format!("$this->{name}"))
            }
            "T_DOUBLE_COLON" => Some(format!("{}::{name}", owner())),
            _ => Some(name.to_owned()),
        }
    }
}
