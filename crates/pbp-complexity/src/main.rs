//! Score Python or PHP functions for pedro-best-practices' measure_complexity.py.
//!
//! Usage: pbp-complexity (python|php) FILE...   (prints JSON)
//!
//! Prints {path: [function] or {"error": message}} in argument order, a file that does not read or parse
//! carrying its error instead of its functions. See scorer.rs for the metrics and each language module for
//! its mappings.

use std::process::ExitCode;

use serde_json::{Map, Value, json};

use pbp_complexity::{php, python, scorer::Function};

type Analyze = fn(&str) -> Result<Vec<Function>, String>;

fn analyzer(language: &str) -> Option<Analyze> {
    match language {
        "python" => Some(python::analyze),
        "php" => Some(php::analyze),
        _ => None,
    }
}

fn measure(analyze: Analyze, path: &str) -> Value {
    let scored = std::fs::read(path)
        .map_err(|error| format!("OSError: {error}"))
        .and_then(|bytes| {
            String::from_utf8(bytes).map_err(|error| format!("UnicodeDecodeError: {error}"))
        })
        .and_then(|source| analyze(&source));
    match scored {
        Ok(functions) => json!(functions),
        Err(message) => json!({ "error": message }),
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some((language, paths)) = args.split_first() else {
        eprintln!("usage: pbp-complexity (python|php) FILE...");
        return ExitCode::from(2);
    };
    let Some(analyze) = analyzer(language) else {
        eprintln!("pbp-complexity: unknown language {language:?}; expected python or php");
        return ExitCode::from(2);
    };
    let report: Map<String, Value> = paths
        .iter()
        .map(|path| (path.clone(), measure(analyze, path)))
        .collect();
    println!("{}", Value::Object(report));
    ExitCode::SUCCESS
}
