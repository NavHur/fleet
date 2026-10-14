# TypeScript patterns

Code examples for each rule in `SKILL.md`. The underlying principles are language-agnostic; see the **type-system-discipline** (`~/.agents/skills/principle-type-system-discipline/SKILL.md`) and **boundary-discipline** (`~/.agents/skills/principle-boundary-discipline/SKILL.md`) principles.

## Branded types

Brand primitives so they can't be mixed up. Validate once at creation; downstream code trusts the type.

```ts
type AgentId = string & { readonly __brand: "AgentId" };

function parseAgentId(input: string): AgentId {
  if (!isUUID(input)) throw new Error(`Invalid agent id: ${input}`);
  // SAFETY: isUUID checked the format the brand promises.
  return input as AgentId;
}

function focusAgent(id: AgentId): void {
  /* input is trusted */
}
```

Match the `readonly __brand: 'X'` shape; don't invent a new convention. With zod, `z.string().uuid().brand<"AgentId">()` validates and brands in one step, with no cast.

## Discriminated unions

If a bug forces the question "wait, can this combination actually happen?", the type is too loose. Model variants with a literal discriminant: every variant shares the field name and each variant's value is unique, so impossible combos can't be represented.

```ts
// Don't. Boolean + optionals lets contradictory states exist.
type DiffState = { loading: boolean; diff?: GitDiff; error?: string };

// Do. Only valid states exist.
type DiffState =
  | { kind: "loading" }
  | { kind: "ready"; diff: GitDiff }
  | { kind: "error"; error: string };
```

Pick one discriminant name (`kind`, `type`, `tag`) and stick to it.

## Constructive modeling

Build the type from parts that are all legal instead of restricting a loose type with runtime checks. Adding is easier than subtracting.

Non-empty, via a variadic tuple:

```ts
type NonEmpty<T> = [T, ...T[]];

// Don't: T[] plus a length check every caller must repeat
function pickWinner(entries: string[]): string {
  if (entries.length === 0) throw new Error("no entries");
  return entries[Math.floor(Math.random() * entries.length)];
}

// Do: an empty value of the type can't exist
function pickWinner(entries: NonEmpty<string>): string {
  return entries[Math.floor(Math.random() * entries.length)];
}
```

Where a plain `T[]` arrives, narrow once with a guard. The fact then travels in the type:

```ts
const isNonEmpty = <T>(arr: T[]): arr is NonEmpty<T> => arr.length > 0;
```

Even length, as pairs. TypeScript has no refinement types (no `arr.length % 2 === 0` at the type level); you don't need one:

```ts
type Pairs<T> = [T, T][];
```

A time range, as start plus duration:

```ts
// Don't: a comment holds the invariant
type TimeRange = { start: Date; end: Date }; // start <= end

// Do: a negative range can't be written; derive end when needed
type TimeRange = { start: Date; durationMs: number };
```

Keep `durationMs` a plain number. Brand it (per Branded types) only if a raw number could be passed where a duration is expected, not by reflex. A `Pairs<T>` is an even-length list under the interpretation you give it, the same way `{ start, durationMs }` is a range. Pick the representation that makes the bad state unconstructable, then expose the reading you need on top (`pairs.flat()`, a `rangeEnd()` helper).

## Simplest total type

Don't strengthen everything. Keep `T[]` when every operation on it is total:

```ts
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0); // [] is 0, fine
```

Strengthen when the loose type forces a lie at a use site. The tells are `!`, `arr[0] as T`, and a "should never happen" throw:

```ts
// Don't: partiality smuggled past the compiler
function newestSession(sessions: Session[]): Session {
  return sessions.at(0)!;
}

// Do: strengthen the input; the assertion disappears
function newestSession(sessions: NonEmpty<Session>): Session {
  return sessions[0];
}
```

Weakening the result to `Session | undefined` is the other total signature. Either way the empty case lands at the call site, the one place that knows what empty means.

## `unknown` over `any`

`any` disables type checking for everything it touches. External data is `unknown`, but only at the line where it enters: decode it there with the repository's schema library and hand the domain type inward. A function that takes or returns `unknown` passes the decoding problem to every caller; the DCA repos reject both (`anti-slop/no-unknown-parameters`, `anti-slop/no-unknown-returns`).

```ts
// Don't: any switches off checking for everything it reaches
function handle(input: any) {
  return input.foo.bar;
}

// Do: decode where the data enters, then pass the domain type
const Listing = z.object({ id: z.string().uuid(), rentCents: z.number().int() });
type Listing = z.infer<typeof Listing>;

export async function GET(request: Request) {
  const listing = Listing.parse(await request.json());
  return Response.json(summarize(listing));
}

function summarize(listing: Listing) {
  /* input is trusted */
}
```

External sources include RPC payloads, `JSON.parse`, `postMessage`, IPC, file contents, environment variables, database results. Use `safeParse` when bad input is an expected outcome the caller turns into a response, `parse` when it is a bug.

## No `as` casts

Every `as` is a potential runtime crash. Cast only after the type system or a check has verified the claim, and state that check in a `SAFETY:` comment right before the assertion (`anti-slop/require-safety-comment-for-type-assertion` in the DCA repos; `as const` is exempt).

```ts
// Don't
const user = data as User;

// Do. A schema decodes without a cast.
const user = User.parse(data);

// Do, when a cast is unavoidable: say what was checked.
// SAFETY: STATUS_LABELS is a Record<Status, string>, so its keys are exactly Status.
const statuses = Object.keys(STATUS_LABELS) as Status[];
```

When refactoring an `as` out of existing code, identify why TypeScript can't infer:

- Missing discriminant: add one, switch to a discriminated union.
- Overly wide source type (e.g. `Record<string, unknown>`): narrow it.
- Untyped boundary: add a parse function or schema.
- Genuinely inexpressible: use a branded type or `satisfies`.

## Narrowing hierarchy

From best to last-resort:

1. **Discriminated union switch / if.** Compiler narrows automatically.
2. **`in` operator.** `"key" in obj` narrows to variants containing that key.
3. **`instanceof`.** For class instances, such as `Error` subclasses.
4. **User-defined type guard.** When the above aren't enough. `typeof` checks live here or in a schema; the DCA repos reject them elsewhere (`anti-slop/no-runtime-typeof`).
5. **`as` cast.** Only after validation.

```ts
function area(s: Shape): number {
  if ("radius" in s) return Math.PI * s.radius ** 2; // narrowed to circle
  return s.width * s.height; // narrowed to rect
}
```

## Type guards

A guard must actually verify the claim. A lying guard is worse than `as` because the bug hides behind a name that says it's safe.

```ts
function isCircle(s: Shape): s is Shape & { kind: "circle" } {
  return s.kind === "circle";
}
```

Prefer discriminant narrowing when possible. The guard adds a layer the reader has to follow.

## Exhaustiveness

In default arms, assign the discriminant to a `never`-typed local. The compiler errors if a new variant is added without handling.

```ts
// Value-returning switch
function area(s: Shape): number {
  switch (s.kind) {
    case "circle":
      return Math.PI * s.radius ** 2;
    case "rect":
      return s.width * s.height;
    default: {
      const _exhaustive: never = s;
      return _exhaustive;
    }
  }
}

// Void switch
function handle(s: Shape): void {
  switch (s.kind) {
    case "circle":
      drawCircle(s);
      break;
    case "rect":
      drawRect(s);
      break;
    default: {
      const _exhaustive: never = s;
      void _exhaustive;
    }
  }
}
```

Return-style in value-returning switches; void-style in statement switches.

## Errors

Classify each failure the way the **fail-loudly** principle (`~/.agents/skills/principle-fail-loudly/SKILL.md`) does: bad input, an expected outcome, or a bug.

```ts
// Don't: the failure becomes "no listings", and the cause is gone
async function loadListings(countyId: CountyId): Promise<Listing[]> {
  try {
    return await db.listings.byCounty(countyId);
  } catch {
    return [];
  }
}

// Do: add context and keep the cause; the caller decides what the user sees
async function loadListings(countyId: CountyId): Promise<Listing[]> {
  try {
    return await db.listings.byCounty(countyId);
  } catch (error) {
    throw new Error(`Failed to load listings for county ${countyId}`, { cause: error });
  }
}
```

An expected outcome belongs in the return type, so the compiler makes callers handle it:

```ts
type ClaimResult =
  | { kind: "claimed"; voucher: Voucher }
  | { kind: "already-claimed"; claimedAt: Date }
  | { kind: "expired" };
```

- Throw `Error` or a subclass, never a string or a plain object; `instanceof` then narrows it.
- A `?? fallback` claims the value may legitimately be absent. For a required value, throw with what was missing instead.
- Await or return every promise; a floating promise's rejection reaches no handler.

## `satisfies` over `as`

`satisfies` validates without widening literal types.

```ts
// Don't. Widens, loses literal types.
const config = { theme: "dark", cols: 3 } as Config;

// Do. Validates AND preserves literal types.
const config = { theme: "dark", cols: 3 } satisfies Config;
// config.theme is "dark" (literal), not string
```

## Boundary validation

Validate once where data crosses in; trust types inside. See the **boundary-discipline** principle (`~/.agents/skills/principle-boundary-discipline/SKILL.md`).

- **Wire formats** (proto, JSON-RPC): parse with `ignoreUnknownFields` so forward-compatible changes don't break old clients.
- **Persisted JSON:** versioned blob with a try/catch around the parse.
- **Don't re-validate** deep in call chains.

## Schema-derived types

When a `.proto`, OpenAPI spec, GraphQL schema, or database migration already defines a shape, derive from the generated types instead of duplicating them.

```ts
// Don't. Duplicate shape, drifts when the schema changes.
type CheckSummary = {
  totalCount: number;
  checks: { name: string; status: string }[];
};
function renderChecks(s: CheckSummary) {
  /* ... */
}

// Do. Derive from the generated schema type.
import type { ChecksMessage } from "<generated module>";
function renderChecks(s: Pick<ChecksMessage, "totalCount" | "checks">) {
  /* ... */
}
```

Reach for `Pick`, `Omit`, `Parameters`, `ReturnType`, `Awaited`, `typeof` before writing a new interface.

## Object args

```ts
// Don't. Swap two args, still compiles.
openFile(uri, {
  startLineNumber: 10,
  startColumn: 1,
  endLineNumber: 10,
  endColumn: 1,
});

// Do. Order-independent, self-documenting.
openFile({
  uri,
  selection: {
    startLineNumber: 10,
    startColumn: 1,
    endLineNumber: 10,
    endColumn: 1,
  },
});
```

Skip on hot paths: per-frame render, tokenizers, parsers, anything in a tight loop where the allocation cost matters.
