//! Score PHP functions the way complexity_php.py does; see scorer.rs for the metrics.
//!
//! mago's lexer tokenizes each file into the stream `PhpToken::tokenize($source, TOKEN_PARSE)` yields
//! (tokens.rs), and a parser ported line for line from complexity_php.py walks it into statements and
//! expressions. A heredoc PHP's lexer rejects (heredoc.rs) is reported as an error. Language mappings:
//! - `elseif` and `else if` are else-ifs (+1 flat); `else` is +1 flat; the alternative syntax
//!   (`if (...):` ... `endif;`) scores the same.
//! - `switch` and `match` are one structural increment each; every `case` and every non-default `match`
//!   condition is a cyclomatic decision.
//! - `&&`/`and`, `||`/`or`, and `xor` form operator runs. `??`, `??=`, and the short ternary `?:` are
//!   shorthand: cyclomatic decisions, cognitively free.
//! - `break N`/`continue N` with N > 1 and `goto` are +1 flat, like labeled jumps.
//! - Closures and arrow functions nest like any nested function. Recursion: a call to the function's own
//!   name, or `$this->`, `self::`, `static::`, or the class name plus the method's name.

mod control;
mod declarations;
mod expressions;
mod heredoc;
mod names;
mod parser;
pub mod tokens;

use crate::scorer::Function;

/// Score every function in a PHP file, or fail with its lexer error.
pub fn analyze(source: &str) -> Result<Vec<Function>, String> {
    let tokens = tokens::tokenize(source)?;
    parser::Parser::new(tokens).run()
}
