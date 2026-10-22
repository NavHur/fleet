//! `pbp-complexity php` against the skill's probe fixture and hand-written traps where PHP's tokenizer
//! and mago's differ. Every expected score is what the retired `complexity_php.py` reported for the same source.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

/// (cognitive, cyclomatic) keyed by (name, line); cognitive is None where the scorer leaves it out.
type Scores = BTreeMap<(String, u64), (Option<u64>, u64)>;

fn run(path: &Path) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_pbp-complexity"))
        .arg("php")
        .arg(path)
        .output()
        .expect("run pbp-complexity");
    let report: Value = serde_json::from_slice(&output.stdout).expect("JSON report");
    report[path.to_str().unwrap()].clone()
}

/// Write `source` to a scratch file named for the test, and report on it.
fn analyze(test: &str, source: &str) -> Value {
    let directory = std::env::temp_dir().join(format!("pbp-php-{}", std::process::id()));
    std::fs::create_dir_all(&directory).unwrap();
    let path = directory.join(format!("{test}.php"));
    std::fs::write(&path, source).unwrap();
    run(&path)
}

fn scores(report: &Value) -> Scores {
    let functions = report
        .as_array()
        .unwrap_or_else(|| panic!("not rejected: {report}"));
    functions
        .iter()
        .map(|function| {
            let key = (
                function["name"].as_str().unwrap().to_owned(),
                function["line"].as_u64().unwrap(),
            );
            let value = (
                function["cognitive"].as_u64(),
                function["cyclomatic"].as_u64().unwrap(),
            );
            (key, value)
        })
        .collect()
}

fn expected(rows: &[(&str, u64, Option<u64>, u64)]) -> Scores {
    rows.iter()
        .map(|&(name, line, cognitive, cyclomatic)| {
            ((name.to_owned(), line), (cognitive, cyclomatic))
        })
        .collect()
}

fn error(report: &Value) -> &str {
    report["error"]
        .as_str()
        .unwrap_or_else(|| panic!("not rejected: {report}"))
}

#[test]
fn probe_fixture_scores_match_the_python_analyzer() {
    let fixture: PathBuf = [
        env!("CARGO_MANIFEST_DIR"),
        "../../skills/pedro-best-practices/tests/fixtures/probe.php",
    ]
    .iter()
    .collect();
    assert_eq!(
        scores(&run(&fixture)),
        expected(&[
            ("pick", 2, Some(14), 10),
            ("a8", 14, Some(3), 4),
            ("a9", 15, Some(4), 1),
            ("<arrow>", 15, None, 2),
            ("<closure>", 15, None, 2),
            ("a10", 16, Some(1), 3),
            ("a12", 17, Some(0), 3),
            ("a13", 18, Some(2), 2),
            ("a15", 19, Some(3), 5),
            ("a16", 20, Some(10), 6),
            ("K::m", 23, Some(2), 2),
            ("K::s", 24, Some(2), 2),
        ])
    );
}

#[test]
fn keywords_used_as_names_stay_names() {
    let source = "<?php
class K {
    function list($a) { if ($a) { return $this->list($a - 1); } }
    function print() { return self::class; }
}
function f($o) { return $o->class && $o->default; }
";
    assert_eq!(
        scores(&analyze("names", source)),
        expected(&[
            ("K::list", 3, Some(2), 2),
            ("K::print", 4, Some(0), 1),
            ("f", 6, Some(1), 2),
        ])
    );
}

#[test]
fn a_by_reference_function_is_named_for_its_ampersand() {
    let report = analyze("reference", "<?php\nfunction &r($a) { if ($a) {} }\n");
    assert_eq!(scores(&report), expected(&[("&", 2, Some(1), 2)]));
}

#[test]
fn break_levels_read_binary_and_underscored_literals() {
    let source = "<?php
function b($a) { while ($a) { while ($a) { break 0b10; } } }
function u($a) { while ($a) { while ($a) { continue 1_0; } } }
";
    assert_eq!(
        scores(&analyze("breaks", source)),
        expected(&[("b", 2, Some(4), 3), ("u", 3, Some(4), 3)])
    );
}

#[test]
fn a_legacy_octal_break_level_fails_like_python_int() {
    let report = analyze(
        "octal",
        "<?php\nfunction o($a) { while ($a) { break 010; } }\n",
    );
    assert_eq!(
        error(&report),
        "ValueError: invalid literal for int() with base 0: '010'"
    );
}

#[test]
fn a_close_tag_swallows_its_newline_without_shifting_lines() {
    let report = analyze(
        "close_tag",
        "<?php ?>\n<p>\n<?php\nfunction t($a) { if ($a) {} }\n",
    );
    assert_eq!(scores(&report), expected(&[("t", 4, Some(1), 2)]));
}

#[test]
fn interpolation_braces_and_yield_from_leave_scoring_intact() {
    let source = "<?php
function s($a) { $x = \"{$a->b} ${a}\"; if ($a) { return $x; } }
function g($a) { yield from ($a && $a); }
";
    assert_eq!(
        scores(&analyze("strings", source)),
        expected(&[("s", 2, Some(1), 2), ("g", 3, Some(1), 2)])
    );
}

#[test]
fn files_php_cannot_parse_are_rejected() {
    let cases = [
        ("syntax", "<?php\nfunction e( {\n", 2),
        ("heredoc", "<?php\n$a = <<<EOT\n  x\n    EOT;\n", 3),
        ("assign", "<?php\n$a = ['k' = 1];\n", 2),
        ("modifier", "<?php\nstatic class A {}\n", 2),
        ("keyword_constant", "<?php\n$a = [readonly];\n", 2),
    ];
    for (test, source, line) in cases {
        let report = analyze(test, source);
        let message = error(&report);
        assert!(message.starts_with("ParseError: "), "{test}: {message}");
        assert!(
            message.ends_with(&format!("on line {line}")),
            "{test}: {message}"
        );
    }
}
