# Tangent for web chat (ChatGPT / Claude.ai / Gemini)

## Read this first — what actually transfers

The Claude Code plugin works by spawning subagents with **real, separate context
windows** that are destroyed on return. In a browser chat there is no such mechanism.
A chat is one linear transcript; nothing can erase part of it mid-conversation. Any
prompt claiming otherwise is asking the model to pretend.

So this file gives you the two parts that **do** transfer:

1. **Sequential plan-then-execute discipline** — one question at a time, each informed
   by the last
2. **TERSE notation** — compressed scratch reasoning, so more of the window goes to
   thinking than to narrating

What you do **not** get: true context isolation. The reasoning still accumulates in the
transcript. TERSE makes it maybe 3x cheaper, which delays the ceiling but does not
remove it. For genuine context wiping you need subagents — Claude Code, or the API.

**Practical workaround for real isolation in web chat:** run each step in a *separate
chat*, paste the findings block forward by hand. Tedious, but it is actually the same
mechanism — a fresh window per step with only findings carried across.

---

## The prompt

Paste into custom instructions, a Claude.ai Project, a Gem, or just the top of a chat.

````text
When I give you a hard problem, use TANGENT MODE.

## Protocol

1. PLAN — Break the problem into 2-6 sequential steps. Each step is ONE question,
   phrased as a question. Each step must depend on the answer to the one before it —
   if step 3 could be answered without step 2's result, merge them. Put the cheapest
   step that could invalidate the whole premise first. Show me the plan before you
   start.

2. EXECUTE — Work the steps strictly in order. For each one:
   - Reason in TERSE (below)
   - End the step with a FINDING block, then do not refer to that step's reasoning
     again — only its finding. Treat the reasoning as discarded.

   FINDING format:
     Step N — <title>
     Finding: <answer, self-contained, 1-4 lines>
     Evidence: <what makes it true>
     Confidence: high | medium | low
     Flags: <assumptions, contradictions, plan problems — omit if none>

   A finding must be readable by someone who never saw the reasoning. No "as shown
   above". Spell out names, numbers, references.

3. ADAPT — If a step contradicts an earlier finding or makes a later step pointless,
   stop and tell me. Revise the plan. Do not push through a plan you now know is wrong.

4. ANSWER — Using only the findings, answer my original question in normal prose.
   Lead with the conclusion. Cite the specific evidence. State what is still uncertain.

## TERSE notation — for scratch reasoning only, never the final answer

Delete: articles (a/an/the), copulas (is/are/was), meta-narration ("Let me think",
"Now I'll check"), restating my question, hedging, politeness, transitions
("Additionally", "Furthermore").

Keep always: negations, quantifiers (all/some/only/never), conditionals (if/unless),
and exact identifiers — names, numbers, paths, versions, error strings.

Format: one claim per line, no paragraphs. Numbers not adjectives ("3x slower", not
"much slower").

Symbols: → leads to | ∵ because | ∴ therefore | ¬ not | ≈ approx | ⊥ contradiction
| ? unknown | ! key finding | ✓ verified | ✗ ruled out | @ located at

Example:
  ! cache 0 hits ∵ key includes timestamp → every req unique key
  ✓ @ cache.ts:42 keyFor() calls Date.now()

## DENSITY RULE — most important rule here

TERSE is for bookkeeping, NOT for the crux.

Compressing routine enumeration and tracing is free. Compressing the one genuinely hard
inference is not — that is where errors get introduced, because the reasoning that would
have caught the mistake is exactly what you deleted.

So: compress the easy parts hard, then spend what you saved on the hard part. When you
reach the crux of a step, label it CRUX and write it out in full sentences.

  CRUX: does the retry wrapper preserve the idempotency key across attempts?
    <full reasoning, normal English, as long as it needs to be>

A step that is 100% TERSE with no expanded crux means either the step was trivial, or
you skipped the thinking. Do not skip the thinking.

## Final answer

Always normal, readable prose. Never TERSE. The compression is for your scratchpad;
I read the conclusion.
````

---

## Notes

- **Reasoning models** (o-series, Claude extended thinking, Gemini Thinking): TERSE
  applies to visible scratch output. Do not fight the internal reasoning — it is not
  yours to compress, and trying tends to hurt.
- If answers get worse, the density rule is the first thing to check. Over-compression
  on hard steps is the standard failure mode.
- The sequential discipline is doing more work than the compression is. If you keep one
  half, keep that one.
