# Godot

Language reference for `pedro-best-practices`: the scene-script interface cap, Godot ownership patterns, GDScript mappings for the shared rules, and the pointer to the performance rules.

## Interface cap

A script's interface is its configuration surface: what a parent decides when it uses the scene or script. Count, for the script's top-level class:

- `@export` variables, in any `@export_*` form (`@export_group`, `@export_subgroup`, and `@export_category` are headings, not variables);
- `signal` declarations, which play the role of callback props;
- the parameters of `_init` and of a `setup` or `configure` method.

Resource scripts are excluded: their exports are a data schema, like the fields of a type. Public methods are left to gdlint's `max-public-methods`. More than eight is `pedro/godot-interface-cap`; seven and eight pass. Count with the bundled script, which resolves `class_name` chains to exclude Resources:

```sh
<this skill's directory>/scripts/godot_interface.py BASE HEAD   # or EMPTY HEAD for every script
```

It lists each script over the cap with the counted names. Validate each against the scene that uses it before reporting, and apply the ownership question to every one.

## Ownership patterns

The ownership criteria in `SKILL.md` apply; in Godot they usually take these forms:

- **Call down, signal up.** A parent calls methods on its children; a child reports upward with signals and never reaches into its parent (`get_parent()` chains, absolute paths into the tree). A child that does is coupled to one placement.
- **One signal per intent, or one signal with a payload.** `action_bar.gd` emits sixteen signals, one per button, and its parent connects each. Ask whether one `action_requested(action: Action)` signal with an enum would serve the parent better; per-intent signals are idiomatic when handlers differ in kind, and a single payload signal is better when the parent dispatches them all the same way. `inspector_card.gd`'s nine signals all carry `colonist_id`, which the card already knows: a `command_requested(colonist_id, command)` signal removes that repetition.
- **Named data over positional parameters.** `raid_forecast_snapshot.gd`'s `_init` takes twelve positional values, several of them `int`; swapping two is silent. A typed Resource or named fields models the snapshot.
- **Group tuning knobs only when they are one concept.** A node with ten spring and damping exports (wingmen's `secondary_motion.gd`) can take a `SpringSettings` Resource when several nodes share presets; when every instance is tuned by hand in the Inspector, the exports are the honest interface and the count is an unresolved design issue rather than a fix.
- **Autoloads hold global services, not shared scratch state.** Moving a parent's coordination into an autoload relocates the bag; it does not remove it.
- **Simulation stays out of visual nodes.** Gameplay state lives in plain objects or Resources that presentation reads; a scene script that owns authoritative state cannot be tested or saved without its scene. Follow the repository's own boundary rules (hexstead's `AGENTS.md` defines them).
- **Resources are shared by reference.** Mutating a loaded Resource changes every holder; runtime state belongs outside it, in a `duplicate()` made by its owner, or in a Resource marked `resource_local_to_scene`.

## Nested conditional expressions

`a if c else (b if d else e)` is nested, with or without the parentheses.

## Complexity mapping

`measure_complexity.py` runs godot-guard's `complexity --json`, the same scorer godot-guard's `check` enforces. Mappings beyond the shared rules:

- `elif` is an else-if (+1 flat); `else` is +1 flat.
- `match` is one structural increment; each non-wildcard branch is a cyclomatic decision, and a `when` guard adds 1 to both metrics.
- `and`/`&&` and `or`/`||` are the same operators; `not` ends a chain.
- Lambdas nest like any nested function, named after the enclosing function (`outer.<lambda#2>`, `outer.named`); property getters and setters score as their own functions (`health.set`).
- Recursion: a call to the function's own name, or `self.` plus that name.

## Performance

Read [godot-performance.md](godot-performance.md) and work through its categories in order: **frame loop, allocation and data, resources and loading, rendering, physics, threading, lifecycle**. Cite findings by the rule's ID.
