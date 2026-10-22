//! Control-flow statements: if/else, loops, switch, try/catch, and `break N`/`continue N`.

use super::parser::{EXPRESSION_END, Parser};

impl Parser<'_> {
    pub(super) fn if_statement(&mut self) {
        let ends = &["T_ELSEIF", "T_ELSE", "T_ENDIF"];
        self.i += 1;
        self.scorer.structural();
        self.scorer.decision(1);
        self.condition();
        self.nested_body(ends);
        loop {
            let else_if = self.kind(0) == "T_ELSE" && self.kind(1) == "T_IF";
            if self.kind(0) == "T_ELSEIF" || else_if {
                self.i += if else_if { 2 } else { 1 };
                self.scorer.fundamental(1);
                self.scorer.decision(1);
                self.condition();
                self.nested_body(ends);
            } else {
                if self.kind(0) == "T_ELSE" {
                    self.i += 1;
                    self.scorer.fundamental(1);
                    self.nested_body(&["T_ENDIF"]);
                }
                break;
            }
        }
        if self.kind(0) == "T_ENDIF" {
            self.i += 1;
            self.expect(";");
        }
    }

    fn nested_body(&mut self, alternative_ends: &[&str]) {
        let region = self.scorer.enter_nesting();
        self.body(alternative_ends);
        self.scorer.leave_nesting(region);
    }

    pub(super) fn loop_statement(&mut self, alternative_end: &str) {
        self.i += 1;
        self.scorer.structural();
        self.scorer.decision(1);
        self.condition();
        self.nested_body(&[alternative_end]);
        if self.kind(0) == alternative_end {
            self.i += 1;
            self.expect(";");
        }
    }

    pub(super) fn do_while(&mut self) {
        self.i += 1;
        self.scorer.structural();
        self.scorer.decision(1);
        let region = self.scorer.enter_nesting();
        self.statement();
        self.scorer.leave_nesting(region);
        self.expect("T_WHILE");
        self.condition();
        self.expect(";");
    }

    pub(super) fn switch(&mut self) {
        self.i += 1;
        self.scorer.structural();
        self.condition();
        let (end, closer) = if self.kind(0) == "{" {
            let closer = self.closer(self.i, self.tokens.len());
            self.i += 1;
            (None, closer)
        } else {
            self.expect(":");
            (Some("T_ENDSWITCH"), self.tokens.len())
        };
        while !self.at_end() && self.i < closer && end != Some(self.kind(0)) {
            self.switch_entry();
        }
        match end {
            None => self.i = closer + 1,
            Some(_) => {
                self.i += 1;
                self.expect(";");
            }
        }
    }

    fn switch_entry(&mut self) {
        match self.kind(0) {
            "T_CASE" => {
                self.scorer.decision(1);
                self.i += 1;
                self.expression(&[":", ";"], None);
                self.i += 1;
            }
            "T_DEFAULT" => {
                self.i += 1;
                self.expect(":");
                self.expect(";");
            }
            _ => {
                let before = self.i;
                let region = self.scorer.enter_nesting();
                self.statement();
                self.scorer.leave_nesting(region);
                self.advance_if_stalled(before);
            }
        }
    }

    pub(super) fn try_statement(&mut self) {
        self.i += 1;
        self.block();
        while self.kind(0) == "T_CATCH" {
            self.i += 1;
            self.scorer.structural();
            self.scorer.decision(1);
            self.skip_group(); // caught types
            let region = self.scorer.enter_nesting();
            self.block();
            self.scorer.leave_nesting(region);
        }
        if self.kind(0) == "T_FINALLY" {
            self.i += 1;
            self.block();
        }
    }

    /// `break N` and `continue N` past one level are +1 flat, like labeled jumps.
    pub(super) fn jump(&mut self) {
        self.i += 1;
        if self.kind(0) == "T_LNUMBER" {
            match python_int(self.text(0)) {
                Ok(levels) if levels > 1 => self.scorer.fundamental(1),
                Ok(_) => {}
                Err(error) => self.fail(error),
            }
        }
        self.skip_until(EXPRESSION_END);
    }
}

/// Python's `int(text, 0)`, which the retired complexity_php.py applied to the level of `break N`. It rejects
/// PHP's legacy octal (`010`), where the Python analyzer crashed; the caller reports that as the file's error.
fn python_int(text: &str) -> Result<u128, String> {
    let invalid = || format!("ValueError: invalid literal for int() with base 0: '{text}'");
    let lower = text.to_ascii_lowercase();
    let (digits, radix) = match lower.get(..2) {
        Some("0x") => (&text[2..], 16),
        Some("0o") => (&text[2..], 8),
        Some("0b") => (&text[2..], 2),
        _ => (text, 10),
    };
    // After a base prefix one underscore may lead; elsewhere underscores only separate digits.
    let digits = match radix {
        10 => digits,
        _ => digits.strip_prefix('_').unwrap_or(digits),
    };
    let separated = !digits.is_empty()
        && !digits.starts_with('_')
        && !digits.ends_with('_')
        && !digits.contains("__");
    let plain: String = digits.chars().filter(|&c| c != '_').collect();
    let leading_zero = radix == 10 && plain.starts_with('0') && plain.bytes().any(|b| b != b'0');
    if !separated || leading_zero {
        return Err(invalid());
    }
    plain.chars().try_fold(0u128, |value, c| {
        let digit = c.to_digit(radix).ok_or_else(invalid)?;
        Ok(value
            .saturating_mul(u128::from(radix))
            .saturating_add(u128::from(digit)))
    })
}

#[cfg(test)]
mod tests {
    use super::python_int;

    #[test]
    fn python_int_reads_integer_literals_like_python() {
        assert_eq!(python_int("2"), Ok(2));
        assert_eq!(python_int("1_0"), Ok(10));
        assert_eq!(python_int("0b10"), Ok(2));
        assert_eq!(python_int("0X1f"), Ok(31));
        assert_eq!(python_int("0o17"), Ok(15));
        assert_eq!(python_int("0x_2"), Ok(2));
        assert_eq!(python_int("00"), Ok(0));
        assert_eq!(python_int("0_0"), Ok(0));
        assert!(python_int("010").is_err());
        assert!(python_int("0_10").is_err());
        assert!(python_int("1__0").is_err());
    }
}
