//! Heredoc and nowdoc indentation, which PHP's lexer checks and mago's does not: every body line must be
//! indented at least as far as the closing marker, with tabs or spaces but not both. Blank lines and lines
//! that start inside an `{$...}` interpolation are exempt.

use mago_syntax::token::TokenKind as K;

/// One document being lexed: where its body starts and which byte ranges are interpolated code.
pub struct Document {
    body_start: usize,
    open: Vec<usize>,
    code: Vec<(usize, usize)>,
}

impl Document {
    pub fn new(body_start: usize) -> Self {
        Document {
            body_start,
            open: Vec::new(),
            code: Vec::new(),
        }
    }

    /// Track a token inside the document's body, so interpolated lines are exempt.
    pub fn see(&mut self, kind: K, offset: usize) {
        match kind {
            K::LeftBrace | K::DollarLeftBrace => self.open.push(offset),
            K::RightBrace => {
                if let Some(start) = self.open.pop()
                    && self.open.is_empty()
                {
                    self.code.push((start, offset));
                }
            }
            _ => {}
        }
    }

    /// Check the body against the closing marker `end`, which starts at `end_offset`.
    pub fn check(&self, source: &str, end_offset: usize, end: &str) -> Result<(), String> {
        let indentation = &end[..end.len() - end.trim_start_matches([' ', '\t']).len()];
        let Some(unit) = indentation.chars().next() else {
            return Ok(());
        };
        if indentation.chars().any(|c| c != unit) {
            return Err(mixed(source, end_offset));
        }
        let body = &source[self.body_start..end_offset];
        for start in line_starts(body).map(|start| self.body_start + start) {
            if !self.interpolated(start) {
                check_line(source, start, unit, indentation.len())?;
            }
        }
        Ok(())
    }

    fn interpolated(&self, offset: usize) -> bool {
        self.code
            .iter()
            .any(|&(open, close)| open < offset && offset <= close)
    }
}

/// Offsets within `body` where its lines start; the text after the last newline is the marker's line.
fn line_starts(body: &str) -> impl Iterator<Item = usize> + '_ {
    let bytes = body.as_bytes();
    let after_newlines = (0..bytes.len()).filter_map(move |index| {
        let ends_line = bytes[index] == b'\n'
            || (bytes[index] == b'\r' && bytes.get(index + 1) != Some(&b'\n'));
        (ends_line && index + 1 < bytes.len()).then_some(index + 1)
    });
    (!body.is_empty())
        .then_some(0)
        .into_iter()
        .chain(after_newlines)
}

fn check_line(source: &str, start: usize, unit: char, width: usize) -> Result<(), String> {
    let line = &source[start..];
    let mut indent = 0;
    for c in line
        .chars()
        .take(width)
        .take_while(|c| matches!(c, ' ' | '\t'))
    {
        if c != unit {
            return Err(mixed(source, start));
        }
        indent += 1;
    }
    let blank = matches!(line[indent..].chars().next(), Some('\n' | '\r') | None);
    if indent < width && !blank {
        let line_number = line_of(source, start);
        return Err(format!(
            "ParseError: Invalid body indentation level (expecting an indentation level of at least {width}) on line {line_number}"
        ));
    }
    Ok(())
}

fn mixed(source: &str, offset: usize) -> String {
    let line = line_of(source, offset);
    format!("ParseError: Invalid indentation - tabs and spaces cannot be mixed on line {line}")
}

fn line_of(source: &str, offset: usize) -> usize {
    1 + source.as_bytes()[..offset]
        .iter()
        .filter(|&&byte| byte == b'\n')
        .count()
}
