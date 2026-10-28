# Svelte

Language reference for `pedro-best-practices`: the component prop cap for Svelte 4 and 5, Svelte ownership patterns, and Svelte performance categories.

## Prop cap

A component's interface is its application-defined props, reported as `pedro/eight-prop-cap`. [prop-counting.md](prop-counting.md) governs the general semantics (public contract over one call site, nested object as one prop, inherited HTML attribute types excluded, unknowns kept unresolved); count these as props:

- **Svelte 5**: every name destructured from `$props()` or declared in its type, including `$bindable()` props, callback props (`onselect`), `children`, and named snippet props. `...rest` typed as HTML attributes adds nothing; an untyped or open rest makes the count a lower bound.
- **Svelte 4**: every `export let` and `export function`/`export const` the caller can set or call, every named `<slot>` and the default slot when the component renders one, and every event name passed to a `createEventDispatcher` dispatch. Forwarded DOM events (`on:click` with no handler) count like callback props.

## Ownership patterns

The ownership criteria in `rules.md` apply. In Svelte, prefer a snippet or slot when the caller owns the rendered content, derive internal state with `$derived` (or a `$:` statement in Svelte 4) instead of asking the caller for it, and use context (`setContext`) only when it removes coordination across several levels rather than relocating one parent's props.

## Complexity mapping

`measure_complexity.py` measures functions in `<script>` blocks (oxlint reads `.svelte` script blocks). Template expressions and Svelte 4 `$:` statements outside functions are not scored; inspect them for nested conditionals by hand.

## Performance

No external reference covers Svelte. Cite findings by these IDs and work through the categories in order: **reactivity, lists and DOM, data loading, bundle size**.

**Reactivity**

- `svelte/effect-for-derivation`: an `$effect` that assigns state computed from other state (in Svelte 4, a derived value written in `afterUpdate` or a manual store `subscribe`). Use `$derived` or `$derived.by` (Svelte 4: `$: x = ...`), which tracks dependencies without an extra update pass. Effects are for side effects outside the component's state. A Svelte 4 `$:` assignment is already a reactive declaration, not a finding.
- `svelte/deep-state-for-replaced-data`: large arrays or objects held in `$state` and only ever replaced wholesale. `$state` proxies every nested property; `$state.raw` avoids the proxy when the code reassigns instead of mutating.

**Lists and DOM**

- `svelte/unkeyed-each`: an `{#each}` over a list that reorders, inserts, or removes items without a key (`{#each items as item (item.id)}`). Unkeyed blocks update by index, so item state and DOM nodes attach to the wrong item and more nodes change than necessary.

**Data loading (SvelteKit)**

- `sveltekit/load-waterfall`: sequential `await`s in a `load` function, or an early `await parent()`, for requests that do not depend on each other. Start independent requests together (`Promise.all`) and call `parent()` after them.

**Bundle size**

- `svelte/eager-heavy-import`: a large dependency or rarely shown component imported at the top of a page. Load it with a dynamic `import()` where it is needed.
