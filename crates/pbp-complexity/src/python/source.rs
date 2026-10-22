//! The source text as the retired complexity_python.py saw it: read in text mode, numbered by CPython's lines, and
//! split by `str.splitlines` for its `elif` check.

use std::borrow::Cow;

use ruff_text_size::TextSize;

/// What Python's text mode does on read: `\r\n` and a lone `\r` both become `\n`.
pub fn universal_newlines(source: &str) -> Cow<'_, str> {
    if !source.contains('\r') {
        return Cow::Borrowed(source);
    }
    Cow::Owned(source.replace("\r\n", "\n").replace('\r', "\n"))
}

/// Characters `str.splitlines` breaks on, besides `\n` and `\r`.
const SPLITLINES_BREAKS: [char; 8] = [
    '\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\u{85}', '\u{2028}', '\u{2029}',
];

fn is_splitlines_break(character: char) -> bool {
    character == '\n' || character == '\r' || SPLITLINES_BREAKS.contains(&character)
}

/// Line numbers and the `elif` check over newline-translated source.
pub struct Lines<'a> {
    /// Byte offset of each CPython line's first character; CPython breaks lines on `\n` alone.
    starts: Vec<usize>,
    /// `source.splitlines()`, which the reference indexes by CPython line numbers even where they disagree.
    split: Vec<&'a str>,
}

impl<'a> Lines<'a> {
    pub fn new(source: &'a str) -> Self {
        let starts = std::iter::once(0)
            .chain(source.match_indices('\n').map(|(index, _)| index + 1))
            .collect();
        let mut split: Vec<&str> = source.split(is_splitlines_break).collect();
        if split.last() == Some(&"") {
            split.pop();
        }
        Lines { starts, split }
    }

    /// 1-based CPython line of a byte offset.
    pub fn line(&self, offset: TextSize) -> usize {
        let offset = offset.to_usize();
        self.starts.partition_point(|&start| start <= offset)
    }

    /// The reference's `is_elif`: the `splitlines` line at the node's CPython line number, from its byte
    /// column taken as a character index, starts with `elif`.
    pub fn is_elif(&self, offset: TextSize) -> bool {
        let line = self.line(offset);
        let column = offset.to_usize() - self.starts[line - 1];
        let Some(text) = self.split.get(line - 1) else {
            return false;
        };
        text.chars().skip(column).take(4).eq("elif".chars())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_breaks_shift_the_elif_check() {
        let source = "a\x0cb\nelif\n";
        let lines = Lines::new(source);
        assert_eq!(lines.line(TextSize::new(4)), 2);
        // Line 2 of splitlines is "b", so the elif at line 2 column 0 does not read as one.
        assert!(!lines.is_elif(TextSize::new(4)));
        assert!(Lines::new("x\nelif y:\n").is_elif(TextSize::new(2)));
    }

    #[test]
    fn universal_newlines_translate_cr_and_crlf() {
        assert_eq!(universal_newlines("a\r\nb\rc\n"), "a\nb\nc\n");
    }
}
