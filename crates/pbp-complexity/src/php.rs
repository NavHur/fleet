//! Score PHP functions the way complexity_php.py does; see scorer.rs for the metrics.
//!
//! mago's lexer tokenizes each file into the stream `PhpToken::tokenize($source, TOKEN_PARSE)` yields
//! (tokens.rs), and a parser ported line for line from complexity_php.py walks it into statements and
//! expressions. A file PHP's parser rejects is reported as an error, as PHP's ParseError is: mago's parser
//! decides (syntax.rs), plus the grammar rules it leaves to later analysis (grammar.rs) and PHP's heredoc
//! indentation (heredoc.rs). Language mappings:
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
mod grammar;
mod heredoc;
mod modifiers;
mod names;
mod parser;
mod syntax;
pub mod tokens;

use crate::scorer::Function;

/// Score every function in a PHP file, or fail with its syntax error.
pub fn analyze(source: &str) -> Result<Vec<Function>, String> {
    syntax::check(source)?;
    let tokens = tokens::tokenize(source)?;
    parser::Parser::new(tokens).run()
}
