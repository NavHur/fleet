//! `pbp-complexity python` against the scores complexity_python.py gives on CPython 3.15: the shared
//! fixtures, then one case per place the port could drift from the reference.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};

use serde_json::Value;

/// (name, line, end_line, cognitive, cyclomatic)
type Row = (String, usize, usize, Option<usize>, usize);

fn run(path: &Path) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_pbp-complexity"))
        .arg("python")
        .arg(path)
        .output()
        .expect("the binary runs");
    assert!(output.status.success(), "{output:?}");
    let report: Value = serde_json::from_slice(&output.stdout).expect("JSON output");
    report[path.to_str().expect("UTF-8 path")].clone()
}

fn rows(value: &Value) -> Result<Vec<Row>, String> {
    if let Some(error) = value.get("error") {
        return Err(error.as_str().expect("a message").to_owned());
    }
    let functions = value.as_array().expect("a function list");
    Ok(functions
        .iter()
        .map(|f| {
            let number = |key: &str| f[key].as_u64().expect("a count") as usize;
            let name = f["name"].as_str().expect("a name").to_owned();
            let cognitive = f["cognitive"].as_u64().map(|value| value as usize);
            (
                name,
                number("line"),
                number("end_line"),
                cognitive,
                number("cyclomatic"),
            )
        })
        .collect())
}

fn fixture(name: &str) -> Vec<Row> {
    let path: PathBuf = [
        env!("CARGO_MANIFEST_DIR"),
        "../../skills/pedro-best-practices/tests/fixtures",
        name,
    ]
    .iter()
    .collect();
    rows(&run(&path)).expect("the fixture parses")
}

fn score(source: &[u8]) -> Result<Vec<Row>, String> {
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "pbp-complexity-python-{}-{unique}.py",
        std::process::id()
    ));
    std::fs::write(&path, source).expect("temp file");
    let scored = rows(&run(&path));
    std::fs::remove_file(&path).expect("temp file");
    scored
}

fn row(name: &str, lines: (usize, usize), cognitive: Option<usize>, cyclomatic: usize) -> Row {
    (name.to_owned(), lines.0, lines.1, cognitive, cyclomatic)
}

/// (name, line, cognitive, cyclomatic), as test_complexity.py compares them.
fn scores(rows: Vec<Row>) -> Vec<(String, usize, Option<usize>, usize)> {
    rows.into_iter()
        .map(|(name, line, _, cognitive, cyclomatic)| (name, line, cognitive, cyclomatic))
        .collect()
}

fn named(
    entries: &[(&str, usize, Option<usize>, usize)],
) -> Vec<(String, usize, Option<usize>, usize)> {
    entries
        .iter()
        .map(|&(name, line, cognitive, cyclomatic)| (name.to_owned(), line, cognitive, cyclomatic))
        .collect()
}

#[test]
fn probe_fixture_scores() {
    assert_eq!(
        scores(fixture("probe.py")),
        named(&[
            ("pick", 1, Some(14), 10),
            ("a1", 14, Some(2), 4),
            ("a2", 18, Some(3), 3),
            ("a5", 25, Some(7), 5),
            ("a8", 31, Some(3), 4),
            ("a9", 33, Some(2), 1),
            ("<lambda>", 34, None, 2),
            ("a13", 36, Some(2), 2),
            ("a14", 38, Some(1), 2),
            ("K.m", 43, Some(2), 2),
        ])
    );
}

#[test]
fn methods_recurse_only_through_self() {
    assert_eq!(
        scores(fixture("class_recursion.py")),
        named(&[
            ("walk", 1, Some(2), 2),
            ("Tree.walk", 6, Some(0), 1),
            ("Tree.depth", 9, Some(2), 2),
        ])
    );
}

#[test]
fn lambdas_come_out_in_ast_field_order() {
    // Call args before keywords; a dict's keys before its values.
    let source = b"f(lambda: a or b, k=lambda: c)(lambda: d or e or g)\n\
x = {lambda: 1: lambda: a or b, lambda: c or d or e: 1}\n";
    let cyclomatic: Vec<usize> = score(source.as_ref())
        .unwrap()
        .iter()
        .map(|r| r.4)
        .collect();
    assert_eq!(cyclomatic, [2, 1, 3, 1, 3, 2]);
}

#[test]
fn decorators_and_defaults_precede_the_function_and_annotations_are_skipped() {
    let source = b"@d(lambda: a or b)\n\
def f(p=lambda: c, *, q=lambda: d or e, r: (lambda: 1) = 2) -> (lambda: 1):\n    return p\n";
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [
            row("<lambda>", (1, 1), Some(1), 2),
            row("<lambda>", (2, 2), Some(0), 1),
            row("<lambda>", (2, 2), Some(1), 2),
            row("f", (2, 3), Some(0), 1),
        ]
    );
}

#[test]
fn a_decorated_function_starts_at_its_def() {
    let source = b"@d\n@e(\n    1)\nasync def f():\n    pass\n";
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [row("f", (4, 5), Some(0), 1)]
    );
}

#[test]
fn elif_is_flat_but_else_then_if_nests() {
    let source = concat!(
        "def f(x):\n    if x:\n        pass\n    elif x:\n        pass\n",
        "    else:\n        if x:\n            pass\n",
    );
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [row("f", (1, 8), Some(5), 4)]
    );
}

#[test]
fn the_elif_check_reads_splitlines_lines() {
    // The form feed splits line 2 for `str.splitlines`, so the reference reads the wrong line at the elif and
    // scores it as an else holding a nested if.
    let source =
        b"def f(x):\n    s = 'a\x0cb'\n    if x:\n        pass\n    elif x:\n        pass\n";
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [row("f", (1, 6), Some(4), 3)]
    );
}

#[test]
fn crlf_and_lone_cr_end_lines() {
    let source = b"def f():\r\n    return 1\r\n\r\ndef g():\r    return 2\r";
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [row("f", (1, 2), Some(0), 1), row("g", (4, 5), Some(0), 1)]
    );
}

#[test]
fn recursion_counts_once_through_the_scope_own_name() {
    let source = concat!(
        "class A:\n    def m(self):\n        self.m()\n        cls.m()\n",
        "    def n(self):\n        n()\ndef top():\n    top()\n    top()\n",
    );
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [
            row("A.m", (2, 4), Some(1), 1),
            row("A.n", (5, 6), Some(0), 1),
            row("top", (7, 9), Some(1), 1),
        ]
    );
}

#[test]
fn capture_and_wildcard_cases_are_not_decisions_unless_guarded() {
    let source = concat!(
        "def f(x):\n    match x:\n        case 1: pass\n        case y: pass\n",
        "        case _: pass\n        case _ if x: pass\n",
    );
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [row("f", (1, 6), Some(2), 4)]
    );
}

#[test]
fn comprehension_clauses() {
    let source = b"def f(y):\n    return [a for a in y if a if a for b in a if b]\n";
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [row("f", (1, 2), Some(4), 6)]
    );
}

#[test]
fn template_strings_type_parameters_and_annotations_are_walked() {
    let source = b"def f(x):\n    return f'{x if x else 0:{\">\" if x else \"<\"}}', t'{x or 1}'\n\
type T[U: (lambda: a or b)] = int\nv: (lambda: c or d or e) = 1\n";
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [
            row("f", (1, 2), Some(3), 4),
            row("<lambda>", (3, 3), Some(1), 2),
            row("<lambda>", (4, 4), Some(1), 3),
        ]
    );
}

#[test]
fn boolean_operator_runs() {
    let source = b"def f(a, b, c):\n    return a and b or c and (a or b)\n";
    assert_eq!(
        score(source.as_ref()).unwrap(),
        [row("f", (1, 2), Some(4), 5)]
    );
}

#[test]
fn rejects_what_cpython_rejects() {
    let rejected: [&[u8]; 9] = [
        b"x = 'a\0b'\n",
        b"\xef\xbb\xbfx = 1\n",
        b"x = '\xe9'\n",
        b"if x:\n\tif y:\n        pass\n",
        b"'''doc'''\nfrom __future__ import nope\n",
        b"from __future__ import braces\n",
        b"def f():\n    lazy from __future__ import annotations\n",
        b"from __future__ import barry_as_FLUFL\n1 != 2\n",
        b"del f()\n",
    ];
    for source in rejected {
        assert!(
            score(source).is_err(),
            "{:?}",
            String::from_utf8_lossy(source)
        );
    }
}

#[test]
fn accepts_what_cpython_accepts() {
    let accepted: [&[u8]; 5] = [
        b"x = 1\nfrom __future__ import nope\n",
        b"\x0cx = 1\n",
        b"if x:\n\tif y:\n\t\tpass\n",
        b"try:\n    pass\nexcept A, B:\n    pass\n",
        b"lazy import a\nprint([*x for x in y])\n",
    ];
    for source in accepted {
        assert_eq!(
            score(source),
            Ok(vec![]),
            "{:?}",
            String::from_utf8_lossy(source)
        );
    }
}
