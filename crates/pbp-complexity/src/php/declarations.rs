//! Declarations: classes and their members, named functions, closures, arrow functions, and `match`.

use super::parser::Parser;

const MODIFIERS: &[&str] = &[
    "T_PUBLIC",
    "T_PROTECTED",
    "T_PRIVATE",
    "T_STATIC",
    "T_ABSTRACT",
    "T_FINAL",
    "T_READONLY",
    "T_VAR",
];

impl Parser<'_> {
    /// `function name(` rather than a closure's `function (`. PHP names a by-reference `&` for what follows
    /// it, never plain "&", so like the Python this never skips one.
    pub(super) fn named_function_follows(&self) -> bool {
        let offset = if self.kind(1) == "&" { 2 } else { 1 };
        !matches!(self.kind(offset), "(" | "EOF")
    }

    pub(super) fn class_declaration(&mut self, name: Option<String>) {
        self.i += 1;
        let name = name.or_else(|| (self.kind(0) == "T_STRING").then(|| self.text(0).to_owned()));
        self.skip_until(&["{"]);
        self.class_body(&name.unwrap_or_else(|| "class@anonymous".to_owned()));
    }

    fn class_body(&mut self, name: &str) {
        let closer = self.closer(self.i, self.tokens.len());
        self.i += 1;
        while self.i < closer && !self.at_end() {
            let before = self.i;
            self.member(name);
            self.advance_if_stalled(before);
        }
        self.i = closer + 1;
    }

    fn member(&mut self, class_name: &str) {
        match self.kind(0) {
            "T_FUNCTION" => self.function_declaration(Some(class_name)),
            "T_ATTRIBUTE" => {
                self.skip_group();
            }
            kind if MODIFIERS.contains(&kind) => self.i += 1,
            "T_USE" => {
                self.skip_until(&[";", "{"]);
                if self.kind(0) == "{" {
                    self.skip_group();
                } else {
                    self.i += 1;
                }
            }
            // Properties, constants, enum cases.
            "{" => {
                self.skip_until(&[";"]);
                self.expect(";");
            }
            _ => {
                self.skip_until(&[";", "}"]);
                self.expect(";");
            }
        }
    }

    pub(super) fn function_declaration(&mut self, class_name: Option<&str>) {
        let start = self.i;
        self.i += 1;
        self.expect("&");
        let name = self.text(0).to_owned();
        self.i += 1;
        if self.kind(0) == "(" {
            self.skip_group(); // parameters, including nullable types
        }
        self.skip_until(&["{", ";"]);
        if self.kind(0) == ";" {
            // An abstract or interface method.
            self.i += 1;
            return;
        }
        let closer = self.closer(self.i, self.tokens.len() - 1);
        let (qualified, own) = match class_name {
            Some(class) => {
                let forms = [
                    format!("$this->{name}"),
                    format!("self::{name}"),
                    format!("static::{name}"),
                    format!("{class}::{name}"),
                ];
                (format!("{class}::{name}"), forms.to_vec())
            }
            None => (name.clone(), vec![name]),
        };
        self.scorer
            .function(qualified, self.line(start), self.line(closer), own);
        self.block();
        self.scorer.end_function();
    }

    pub(super) fn closure(&mut self) {
        let start = self.i;
        self.i += 1;
        self.expect("&");
        if self.kind(0) == "(" {
            self.skip_group();
        }
        self.skip_until(&["{"]);
        let closer = self.closer(self.i, self.tokens.len() - 1);
        let (line, end_line) = (self.line(start), self.line(closer));
        self.scorer
            .function("<closure>".to_owned(), line, end_line, Vec::new());
        self.block();
        self.scorer.end_function();
    }

    /// `fn (...) => expression`, which ends where the enclosing expression's stop or limit does.
    pub(super) fn arrow_function(&mut self, stop: &[&str], limit: Option<usize>) {
        let start = self.i;
        self.i += 1;
        self.expect("&");
        if self.kind(0) == "(" {
            self.skip_group();
        }
        self.skip_until(&["T_DOUBLE_ARROW"]);
        self.i += 1;
        let line = self.line(start);
        let function = self
            .scorer
            .function("<arrow>".to_owned(), line, line, Vec::new());
        let mut ends = stop.to_vec();
        ends.extend([",", ")", "]", "}"]);
        self.expression(&ends, limit);
        let last = self.i.saturating_sub(1).max(start);
        self.scorer.functions[function].end_line = self.line(last);
        self.scorer.end_function();
    }

    pub(super) fn match_expression(&mut self) {
        self.i += 1;
        self.scorer.structural();
        self.condition();
        let closer = self.closer(self.i, self.tokens.len());
        self.i += 1;
        while self.i < closer && !self.at_end() {
            let before = self.i;
            if self.kind(0) == "T_DEFAULT" {
                self.i += 1;
            } else {
                self.match_conditions(closer);
            }
            self.expect("T_DOUBLE_ARROW");
            let region = self.scorer.enter_nesting();
            self.expression(&[","], Some(closer));
            self.scorer.leave_nesting(region);
            self.expect(",");
            self.advance_if_stalled(before);
        }
        self.i = closer + 1;
    }

    /// An arm's comma-separated conditions, each a cyclomatic decision.
    fn match_conditions(&mut self, closer: usize) {
        while self.i < closer {
            self.scorer.decision(1);
            self.expression(&[",", "T_DOUBLE_ARROW"], Some(closer));
            if self.kind(0) != "," {
                break;
            }
            self.i += 1;
        }
    }
}
