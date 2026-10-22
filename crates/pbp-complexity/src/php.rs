//! Placeholder: the php analyzer lands in its own commit. tokens.rs turns a file into the token stream
//! `PhpToken::tokenize($source, TOKEN_PARSE)` yields, from mago's lexer.

mod heredoc;
mod names;
pub mod tokens;

use crate::scorer::Function;

pub fn analyze(_source: &str) -> Result<Vec<Function>, String> {
    Err("not implemented".to_owned())
}
