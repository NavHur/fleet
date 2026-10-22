//! Shared scoring for the per-language complexity analyzers.
//!
//! Cognitive complexity follows the SonarSource whitepaper (G. Ann Campbell, v1.7): structural increments
//! cost 1 plus the current nesting, fundamental increments cost 1, nested functions add a nesting level and
//! fold their score into the enclosing top-level function. Cyclomatic complexity follows ESLint's classic
//! `complexity` rule: 1 plus one per decision point, scored for every function on its own. Each analyzer
//! walks its language's syntax tree and calls the methods below; this module owns the arithmetic so every
//! language scores the same way.

use serde::Serialize;

/// One scored function, serialized in the field order measure_complexity.py has always read.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Function {
    pub name: String,
    pub line: usize,
    pub end_line: usize,
    pub cyclomatic: usize,
    /// None for nested functions: counted in the top-level one.
    pub cognitive: Option<usize>,
}

struct Frame {
    /// Index into `Scorer::functions`.
    function: usize,
    nesting: usize,
    recursion_counted: bool,
    own_names: Vec<String>,
}

/// Whether `enter_nesting` raised a level, so `leave_nesting` lowers only what it raised.
#[must_use]
pub struct Nesting(bool);

#[derive(Default)]
pub struct Scorer {
    pub functions: Vec<Function>,
    frames: Vec<Frame>,
}

impl Scorer {
    pub fn active(&self) -> bool {
        !self.frames.is_empty()
    }

    /// Start scoring a function body; `end_function` closes it. `own_names` are the call forms that count
    /// as recursion. Returns the function's index, for analyzers that find its end while parsing.
    pub fn function(
        &mut self,
        name: String,
        line: usize,
        end_line: usize,
        own_names: Vec<String>,
    ) -> usize {
        let (nesting, cognitive) = match self.frames.last() {
            Some(frame) => (frame.nesting + 1, None),
            None => (0, Some(0)),
        };
        self.functions.push(Function {
            name,
            line,
            end_line,
            cyclomatic: 1,
            cognitive,
        });
        let function = self.functions.len() - 1;
        self.frames.push(Frame {
            function,
            nesting,
            recursion_counted: false,
            own_names,
        });
        function
    }

    pub fn end_function(&mut self) {
        self.frames.pop();
    }

    /// Enter a nesting region: the body of an if, else, loop, catch, case, or ternary branch.
    pub fn enter_nesting(&mut self) -> Nesting {
        match self.frames.last_mut() {
            Some(frame) => {
                frame.nesting += 1;
                Nesting(true)
            }
            None => Nesting(false),
        }
    }

    pub fn leave_nesting(&mut self, entered: Nesting) {
        if entered.0 {
            let frame = self
                .frames
                .last_mut()
                .expect("a nesting region closes inside its function");
            frame.nesting -= 1;
        }
    }

    fn top_cognitive(&mut self) -> &mut usize {
        let top = self.frames[0].function;
        self.functions[top]
            .cognitive
            .as_mut()
            .expect("a top-level function has a cognitive score")
    }

    /// if, ternary, switch/match, loop, catch: 1 plus the nesting level.
    pub fn structural(&mut self) {
        if let Some(frame) = self.frames.last() {
            let cost = 1 + frame.nesting;
            *self.top_cognitive() += cost;
        }
    }

    /// else, else-if, operator runs, labeled jumps, recursion: a flat amount each.
    pub fn fundamental(&mut self, amount: usize) {
        if self.active() && amount > 0 {
            *self.top_cognitive() += amount;
        }
    }

    /// A cyclomatic decision point in the innermost function.
    pub fn decision(&mut self, amount: usize) {
        if let Some(frame) = self.frames.last() {
            self.functions[frame.function].cyclomatic += amount;
        }
    }

    /// Count recursion once per function when `form` names the function itself.
    pub fn call(&mut self, form: &str) {
        let Some(frame) = self.frames.last_mut() else {
            return;
        };
        if !frame.recursion_counted && frame.own_names.iter().any(|own| own == form) {
            frame.recursion_counted = true;
            self.fundamental(1);
        }
    }
}

/// Runs of like operators in a flattened boolean chain: `a && b || c` is 2.
pub fn operator_runs<T: PartialEq>(operators: &[T]) -> usize {
    let mut runs = 0;
    let mut previous = None;
    for operator in operators {
        if previous != Some(operator) {
            runs += 1;
            previous = Some(operator);
        }
    }
    runs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nested_functions_fold_cognitive_into_the_top_level_one() {
        let mut scorer = Scorer::default();
        scorer.function("outer".into(), 1, 9, vec!["outer".into()]);
        scorer.structural();
        let region = scorer.enter_nesting();
        scorer.function("inner".into(), 3, 5, vec![]);
        scorer.structural();
        scorer.decision(1);
        scorer.end_function();
        scorer.leave_nesting(region);
        scorer.call("outer");
        scorer.call("outer");
        scorer.end_function();
        let [outer, inner] = &scorer.functions[..] else {
            panic!("two functions")
        };
        // if (1) + the inner if at nesting 2 (3) + recursion once (1).
        assert_eq!((outer.cognitive, outer.cyclomatic), (Some(5), 1));
        assert_eq!((inner.cognitive, inner.cyclomatic), (None, 2));
    }

    #[test]
    fn operator_runs_count_changes_of_operator() {
        assert_eq!(operator_runs(&["and", "and", "or", "and"]), 3);
        assert_eq!(operator_runs::<&str>(&[]), 0);
    }
}
