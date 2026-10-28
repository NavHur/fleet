# PHP

Language reference for `pedro-best-practices`: the component prop cap for Blade and Livewire, PHP mappings for the shared rules, and the absence of a performance reference.

## Prop cap

Blade and Livewire components are UI components, so their interfaces take the cap, reported as `pedro/eight-prop-cap`:

- **Anonymous Blade components**: the entries of `@props([...])`, with or without defaults. Attributes that fall through to `$attributes` are not counted.
- **Class-based Blade components**: the constructor's parameters.
- **Livewire components**: the parameters of `mount()`, or the public properties a parent sets directly (`<livewire:invoice :invoice="$invoice" />`) when there is no `mount()`.

Plain classes and functions have no numeric cap; apply the ownership criteria in `rules.md` to their public APIs.

## Nested conditional expressions

`$a ? $b : ($c ? $d : $e)` is nested. PHP 8 rejects the unparenthesized form, so look for the parenthesized one. The short ternary `?:` and `??` are shorthand, not conditional expressions.

## Complexity mapping

`measure_complexity.py` runs fleet's `pbp-complexity php`, which lexes PHP into the token stream PHP's own tokenizer produces and rejects the files PHP rejects; PHP itself is not needed. Mappings beyond the shared rules:

- `elseif` and `else if` are else-ifs (+1 flat); `else` is +1 flat; the alternative syntax (`if (...):` ... `endif;`) scores the same.
- `switch` and `match` are one structural increment each; every `case` and every non-default `match` condition is a cyclomatic decision.
- `&&`/`and`, `||`/`or`, and `xor` form operator runs. `??`, `??=`, and the short ternary `?:` are cyclomatic decisions and cognitively free.
- `break N`/`continue N` with N > 1 and `goto` are +1 flat, like labeled jumps.
- Closures and arrow functions nest like any nested function and fold into the enclosing method's cognitive score. Filament and Livewire builder methods (`table()`, `form()`) full of `fn () => $x ? ... : ...` callbacks therefore score high even when each callback is simple: recommend extracting column, filter, and field definitions into named methods that each own one decision.
- Recursion: a call to the function's own name, or `$this->`, `self::`, `static::`, or the class name plus the method's name.

## Performance

No performance reference. Report a performance finding only with a concrete, evidenced cost (a query per loop iteration or per table row, eager loading missing for a relation read in a loop, repeated work in a builder callback that runs per row) under `pedro/performance`, and list PHP performance as reviewed without a reference in coverage.
