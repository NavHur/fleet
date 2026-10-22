//! Score Python functions; a port of pedro-best-practices' complexity_python.py, function for function.
//!
//! Language mappings:
//! - `elif` is an else-if (+1 flat); `else` on if, for, and while is +1 flat.
//! - `try`, `else` on try, and `finally` are free; each `except` is structural.
//! - `match` is one structural increment; each non-wildcard `case` is a cyclomatic decision, and a case
//!   guard adds 1 to both metrics.
//! - Comprehensions: each `if` clause and each `for` clause after the first add 1 to both metrics; the first
//!   `for` adds 1 to cyclomatic only.
//! - Recursion: a function calling its own name, or a method calling itself through `self.` or `cls.`.
//!
//! A file is rejected exactly when CPython 3.15's `ast.parse` rejects it; see syntax.rs.

mod syntax;

use crate::scorer::Function;

/// Parsing only for now: a file CPython rejects carries its error, any other scores no functions yet.
pub fn analyze(source: &str) -> Result<Vec<Function>, String> {
    syntax::parse(source)?;
    Ok(Vec::new())
}
