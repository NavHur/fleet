# React

Language reference for `pedro-best-practices`: the component prop cap, React ownership patterns, and Vercel's performance categories.

## Prop cap

A component's interface is its application-defined top-level props. Count them with [prop-counting.md](prop-counting.md), the authoritative counting semantics, and report violations as `pedro/eight-prop-cap`. The cap concerns React props, not ordinary helper-function parameters.

## Ownership patterns

The ownership criteria in `rules.md` apply; in React they usually take these forms:

- Replacing `ctaLabel` and `ctaHref` with a cohesive `cta` is reasonable; replacing seventeen independent inputs with eight bags is insufficient.
- Derive internal IDs inside the owner, pass a field's resolved error instead of whole-form validation, and use explicit variants for fixed combinations. Use children or focused slots when the caller owns the rendered content.
- A dialog that owns its refs, focus handling, and motion removes real caller obligations. A seasonal card that derives its icon and colors from `season` removes decisions that an `appearance` bag merely transports.
- Introduce hooks, context, or compound components only when they reduce actual coordination; moving the same bag into context is not sufficient.

When a candidate needs deeper composition guidance, read the installed [Vercel composition patterns](~/.agents/skills/vercel-composition-patterns/SKILL.md) and its relevant detailed rules.

## Complexity mapping

Nested callbacks inside a component (event handlers, effects, render helpers) fold into the component's cognitive score, so a component's render path is measured as one unit. Each callback still gets its own cyclomatic score.

## Performance

Read the installed [Vercel React best practices](~/.agents/skills/vercel-react-best-practices/SKILL.md) index, then the relevant `rules/*.md` files relative to that directory before validating findings; its compiled `AGENTS.md` is the full expanded reference. Cite findings by the Vercel rule's ID. If the skill is missing, look for it by name; if unavailable, complete the rest of the audit and list performance as a coverage gap.

Work through Vercel's eight categories in order: **waterfalls, bundle size, server performance, client fetching, rerenders, rendering, JavaScript performance, advanced patterns**. Mark categories inapplicable where the repository lacks those features, such as Next.js server features in a client-only React app. Account for framework versions, React Compiler, bundler configuration, and existing fetching and cache patterns.

Settled fact, do not re-check: Next.js optimizes `lucide-react` barrel imports by default (its built-in `optimizePackageImports` list in `next/dist/server/config.js`, line ~1125 in Next 16.3 and ~988 in 16.2), so `import { X } from "lucide-react"` is not a bundle-size finding in NJ Homes Next or Receipt Hub.
