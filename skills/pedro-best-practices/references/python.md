# Python

Language reference for `pedro-best-practices`: Python has no interface cap and no performance reference; the shared rules apply with these mappings.

## Interface

No numeric cap: the eight-input cap covers UI components and scene scripts, not function parameters. Apply the ownership criteria in `SKILL.md` to public module and class APIs: a function whose callers keep passing the same group of values in the same order is a candidate for a cohesive type (a dataclass or `TypedDict`), and a class whose callers must call methods in a fixed order is a candidate for owning that sequence.

## Nested conditional expressions

`x if a else (y if b else z)` is nested, with or without the parentheses, including inside comprehensions and lambdas.

## Complexity mapping

`measure_complexity.py` runs fleet's `pbp-complexity python`, which parses as CPython 3.15's `ast.parse` does, so every older syntax parses too. Mappings beyond the shared rules:

- `elif` is an else-if (+1 flat); `else` on `if`, `for`, and `while` is +1 flat.
- `try`, `else` on `try`, and `finally` are free; each `except` is structural.
- `match` is one structural increment; each non-wildcard `case` is a cyclomatic decision, and a case guard adds 1 to both metrics.
- Comprehensions: each `if` clause and each `for` clause after the first add 1 to both metrics.
- Recursion: a function calling its own name, or a method calling itself through `self.` or `cls.`.

Repository limits in ruff (`[tool.ruff.lint.mccabe] max-complexity`), flake8 (`max-complexity`), or complexipy (`max-complexity-allowed`) tighten the limits automatically; ruff's and complexipy's own scores can differ slightly from the skill's, so report the skill's measurement.

## Performance

No performance reference. Report a performance finding only with a concrete, evidenced cost (a query per loop iteration, repeated parsing of the same input, quadratic membership tests on large lists) under `pedro/performance`, and list Python performance as reviewed without a reference in coverage.
