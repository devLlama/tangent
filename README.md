# Tangent

**Sequential disposable reasoning for Claude Code.**

Claude breaks a hard problem into steps, then thinks each step through in a *throwaway
context window* — reading files, chasing dead ends, verifying things — and brings back
only a compressed finding. The exploration never touches your main conversation.

No API key. Runs on your existing Claude Code session.

---

## The idea

When Claude works through something genuinely hard in your main conversation, two things
go wrong:

1. **The exploration is verbose.** Reading six files to rule out five of them costs
   thousands of tokens, and you only needed the sixth.
2. **It stays there forever.** Every dead end sits in the context window for the rest of
   the session, crowding out the work you actually care about.

Tangent moves that work somewhere disposable. Each step runs in a subagent whose context
is destroyed on return. What survives is a few lines of finding.

```
main context          step 1 ctx      step 2 ctx      step 3 ctx
     │                (disposable)    (disposable)    (disposable)
     ├─ plan ────────────▶ think ─┐
     │                    (wiped)  │
     │◀── finding ────────────────┘
     ├────────────────────────────────▶ think ─┐
     │                                 (wiped)  │   ← starts knowing finding 1
     │◀── finding ─────────────────────────────┘
     ├──────────────────────────────────────────────▶ think ─┐
     │                                                (wiped) │  ← knows findings 1+2
     │◀── finding ───────────────────────────────────────────┘
     └─ synthesize answer from findings only
```

## Why sequential, not parallel

Subagent fan-out already exists, and it is the right tool for search — twelve agents
grepping twelve directories at once.

It is the wrong tool for reasoning, because parallel agents cannot learn from each
other. Each one starts from the same blind position.

Tangent runs strictly in order, so **step 3 begins already knowing what steps 1 and 2
established** and can ask a sharper question than it could have from a cold start. The
chain is the entire value. It also means the plan can be revised mid-run when a step
turns up something that invalidates it.

## Compressed reasoning (TERSE)

Inside the disposable contexts, reasoning is written in a compressed notation — articles
and copulas dropped, symbols for logical connectives, one claim per line.

```
! cache 0 hits ∵ key includes timestamp → every req unique key
✓ @ src/cache.ts:42 keyFor() calls Date.now()
```

versus the ~3x longer prose version of the same two facts.

**The important caveat, which is baked into the prompts:** compression is applied to
bookkeeping, *not* to the crux. Compressing routine enumeration is free. Compressing the
one genuinely hard inference is where errors get introduced — the reasoning that would
have caught the mistake is exactly what got deleted. So steps compress the easy parts
hard and then spend the savings writing the hard part out in full.

## Install

```bash
/plugin marketplace add chrismichaelraj-bharmalcpas/tangent
/plugin install tangent
```

Or clone into a project:

```bash
git clone https://github.com/chrismichaelraj-bharmalcpas/tangent .claude/plugins/tangent
```

## Use

Explicitly:

```
/tangent why does the checkout retry sometimes double-charge?
```

Or just ask — the skill self-triggers on phrasing like *"think this through properly"*,
*"work out why…"*, *"go deep on…"*.

You will see the plan, then a one-line receipt per step, then the answer:

```
Plan:
  1. Does the retry wrapper preserve the idempotency key across attempts?
  2. If not, does the payment provider dedupe server-side on anything else?
  3. Which call sites are exposed?

  Step 1 done. Wrapper regenerates key per attempt @ src/http/retry.ts:88
  Step 2 done. Provider dedupes on idempotency key only — no fallback
  Step 3 done. 2 call sites affected: checkout.ts:141, subscription.ts:67

Double-charge is real and reproducible. buildRequest() generates a fresh UUID on
every call, so retry attempt 2 carries a different idempotency key than attempt 1…

Reasoning ledger: .tangent/checkout-retry-20260805-142233.md
```

## The ledger

Each run writes `.tangent/<slug>-<timestamp>.md` — the question, the plan, and every
step's finding with its evidence and confidence.

Two reasons this exists. Mechanically, it is how findings cross between contexts: the
orchestrator passes a *file path*, not the findings themselves, so during the run the
main context sees only one-line receipts. Findings do reach it — once, already
compressed, at synthesis. What never reaches it is the reasoning that produced them.
Practically, the ledger is your audit trail — when an answer looks wrong, it shows which
step went wrong and how confident it was.

To be exact about the guarantee, since it is easy to overstate: `N` steps cost the main
context roughly `plan + N one-line receipts + the findings section`, instead of `N` full
investigations. The saving is on exploration, not on conclusions — you still pay for
the conclusions, because you need them.

Gitignored by default.

## What's in the box

| Path | What it is |
| --- | --- |
| `skills/tangent/SKILL.md` | Orchestrator — planning, sequencing, synthesis |
| `skills/tangent/reference/notation.md` | TERSE notation spec |
| `agents/tangent-thinker.md` | The disposable reasoner |
| `portable/web-chat-prompt.md` | Paste-in version for ChatGPT / Claude.ai / Gemini |

## Web chat version

`portable/web-chat-prompt.md` adapts this for browser chat — **with a real limitation
stated up front:** a browser chat is one linear transcript and nothing can erase part of
it mid-conversation. There is no way to get true context isolation there.

What transfers is the sequential plan-then-execute discipline and the TERSE notation,
which together make reasoning meaningfully cheaper but not free. If you want actual
isolation in a browser, run each step in a separate chat and paste findings forward by
hand — that is the same mechanism, done manually.

## When not to use it

- The answer is one file read away
- The problem is one step — no chain to build, so the spawn is pure overhead
- Broad search with no dependency between the searches — that is real parallel work,
  use the `Explore` agent
- You want speed on a tight edit loop

Each step costs a subagent spawn. Three good steps beat eight shallow ones.

## Status

v0.1.0, early. The prompts are the product — read them, fork them, tune them to how you
think. `skills/tangent/SKILL.md` is where the interesting decisions live.

## License

MIT
