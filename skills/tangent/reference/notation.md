# TERSE — compressed reasoning notation

Notation for **scratch reasoning inside a disposable context**. Not for user-facing output.

The goal is to spend fewer tokens per unit of reasoning, so more of the budget goes to
*thinking* and less to *narrating the thinking*.

## Rules

**Delete these entirely:**

- Articles — `a`, `an`, `the`
- Copulas — `is`, `are`, `was`, `were`, `be` (when the relation is obvious)
- Meta-narration — "Let me think about", "Now I'll check", "Interesting, so"
- Restating the question back
- Politeness, hedging, self-congratulation ("Great question", "I should be careful here")
- Transitions — "Additionally", "Furthermore", "It's worth noting that"

**Keep these always:**

- Negations (`not`, `no`, `never`) — dropping one inverts a conclusion
- Quantifiers (`all`, `some`, `only`, `never`, `every`)
- Conditionals (`if`, `unless`, `when`)
- Exact identifiers — file paths, line numbers, function names, error strings, versions

**Format:**

- One claim per line. No paragraphs.
- Concrete refs over description: `src/cache.ts:42`, not "the caching module"
- Numbers over adjectives: `3.2x slower`, not "significantly slower"

## Symbols

| Sym | Means             | Sym | Means                    |
| --- | ----------------- | --- | ------------------------ |
| `→` | leads to, implies | `∴` | therefore                |
| `∵` | because           | `¬` | not                      |
| `≈` | approximately     | `⊥` | contradiction / blocked  |
| `?` | unknown, assumed  | `!` | key finding              |
| `✓` | verified          | `✗` | ruled out                |
| `@` | located at        | `>` | greater / better than    |

## Example

Verbose (61 tokens):

> I think the reason the cache isn't working is probably because the cache key
> includes a timestamp. This means that every single request generates a different
> key, and therefore nothing ever hits the cache. I verified this by looking at the
> code in the cache module.

TERSE (19 tokens):

```
! cache 0 hits ∵ key includes timestamp → every req unique key
✓ @ src/cache.ts:42 keyFor() calls Date.now()
```

Same information. Same conclusion. ~3x cheaper.

## The density rule — IMPORTANT

TERSE is for **bookkeeping**, not for the crux.

Compressing routine steps is free. Compressing the one genuinely hard inference is not —
that is where errors get introduced, because the reasoning that would have caught the
mistake is exactly the reasoning you deleted.

So:

- Enumerating, tracing, listing, checking known ground → **compress hard**
- The single hard inference the step turns on → **expand. Write it out. Use full sentences.**

Marking the hard part explicitly is good practice:

```
CRUX: does retry wrapper preserve idempotency key across attempts?
  Full reasoning: the wrapper rebuilds the request object per attempt (line 88),
  and buildRequest() generates a fresh UUID each call, so attempt 2 carries a
  different idempotency key than attempt 1. The server treats them as distinct
  writes. This is the bug.
✓ confirmed @ src/http/retry.ts:88
```

Budget the tokens you saved on the easy parts, spend them on the crux. A step that is
100% TERSE with no expanded crux usually means the step was easy — or that the crux
got skipped.

## Findings must survive the context wipe

Scratch reasoning is discarded. The finding is all that persists into the next step.

So a finding must be **self-contained** — readable by someone who never saw the reasoning:

- ✗ `confirmed, it's the bug` — bad, refers to vanished context
- ✓ `retry wrapper regenerates idempotency key per attempt @ src/http/retry.ts:88 → duplicate writes` — good

Include exact identifiers in findings. The next step cannot look them up in reasoning
that no longer exists.
