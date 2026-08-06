---
name: tangent
description: Think a hard problem through in disposable side contexts instead of the main one. Decomposes the problem into sequential steps, then reasons through each step in a fresh throwaway context using compressed notation, carrying only findings forward. Use for problems that need genuine multi-step reasoning — debugging a subtle failure, tracing a dependency chain, evaluating a design against constraints, working out why something behaves unexpectedly — especially when the investigation would otherwise flood the main conversation with exploration you will not need again. Triggers on "think this through", "work through this properly", "go deep on", "reason it out", "/tangent".
---

# Tangent — sequential disposable reasoning

**Problem:** $ARGUMENTS

## What this does

Hard reasoning is expensive in the main context for two reasons: the exploration is
verbose, and once it is there it stays there, crowding the window for the rest of the
conversation.

This skill moves the reasoning somewhere disposable. Each step runs in a subagent with
a fresh context window that is destroyed on return. Only a compressed finding survives.
The main context ends up holding the conclusions and none of the search.

**This is sequential, not parallel.** That is the point, and it is what separates this
from ordinary subagent fan-out. Parallel agents cannot learn from each other — each one
starts from the same blind position. Here, step 3 begins already knowing what steps 1
and 2 established, so it can ask a sharper question than it could have from a cold
start. The chain is the value. Never run the steps concurrently.

## When NOT to use this

Skip it and just answer directly when:

- The answer is already known, or is one file read away
- The problem has one step — there is no chain to build, so spawning is pure overhead
- The task is broad search across many files with no dependency between the searches —
  that is genuinely parallel work; use the `Explore` agent instead
- You are mid-edit on a tight loop and the user wants speed

Each step costs a subagent spawn. Three good steps beat eight shallow ones.

---

## Phase 0 — Open a ledger

The ledger is the only channel between steps. Reasoning dies; the ledger persists.

Create `.tangent/<slug>-<YYYYMMDD-HHMMSS>.md` in the project root, where `<slug>` is
3-4 kebab-case words from the problem. If `.tangent/` is not in `.gitignore`, add it.

Seed the file:

```markdown
# Tangent: <problem restated in one line>

**Started:** <ISO timestamp>

## Question
<the full problem, verbatim from the user — do not paraphrase, later steps read this
as the source of truth and you are the last one who can see the original>

## Plan
<filled in Phase 1>

## Findings
<appended by each step>
```

## Phase 1 — Plan

Decompose into **2-6 sequential steps**. Write them into `## Plan`, then show the user
the plan as a short numbered list before executing.

A good step:

- **Answers one question**, stated as a question — `Step 2: Does the retry wrapper
  preserve the idempotency key across attempts?` not `Step 2: Look at retries`
- **Depends on the steps before it.** If step 3 could run without step 2's finding,
  the split is doing nothing. Merge them.
- **Is resolvable** — a step whose answer is "it depends" was posed wrong
- **Names its own success condition** where that is not obvious

Order matters: **cheap and decisive first**. A step that could invalidate the whole
premise goes first, so a bad premise dies before you spend five steps on it.

If the problem does not decompose into a dependent chain, say so and answer it
directly. Not every problem is this shape, and forcing one into it wastes spawns.

## Phase 2 — Execute, one step at a time

For each step in order:

```
Agent(
  subagent_type: "tangent-thinker",
  run_in_background: false,        // REQUIRED — sequential, must block
  description: "Tangent step N",
  prompt: "Ledger: <absolute path to ledger file>\nStep: N\n\nRead the ledger for the
           question, plan, and prior findings. Think step N through. Append your finding.
           Return a one-line receipt."
)
```

Rules:

- **`run_in_background: false`, always.** Wait for each step before starting the next.
  Backgrounding them breaks the chain — step 3 would start blind.
- **Pass the ledger path, not the findings.** The subagent reads prior findings from
  the file. If you paste them into the prompt, they land in your context and you have
  paid the cost this tool exists to avoid.
- **Do not read the ledger between steps.** You get the receipt; that is enough to
  decide whether to continue. Reading the full ledger mid-run reintroduces exactly the
  bloat you are avoiding.
- **One spawn per step.** If a step fails or returns nothing useful, do not silently
  retry — see below.

### Reacting to receipts

The receipt is one line plus optional flags. Act on it:

| Receipt says | Do |
| --- | --- |
| Normal finding | Continue to next step |
| `Flag:` prior finding looks wrong | Stop. Tell the user, propose a revised plan |
| `Flag:` later step now pointless | Drop that step, say why |
| Finding unresolved | Either add a step to break the blocker, or continue and note the gap in the final answer — do not paper over it |
| Step errored / returned nothing | Retry **once** with a sharper prompt. If it fails again, stop and report — do not keep spawning |

Revising the plan mid-run is correct behaviour, not failure. That is what sequential
buys you. Update `## Plan` in the ledger when you revise, so later steps see the change.

## Phase 3 — Synthesize

When the chain completes, read **only the `## Findings` section** of the ledger. It is
TERSE-compressed and cheap. Do not read the scratch reasoning — there isn't any, by
design.

Then answer the user's original question in normal prose. Not the plan, not a step
log — the answer.

- Lead with the conclusion
- Support it with the specific evidence from the findings (file:line, numbers, quotes)
- State what remains uncertain, and flag any `low` confidence finding the conclusion
  leans on
- If findings contradict each other, say so plainly rather than quietly picking one

Close with the ledger path, one line, so the user can audit the reasoning:

```
Reasoning ledger: .tangent/retry-idempotency-20260805-142233.md
```

## Notation

Steps reason in TERSE — see `reference/notation.md`. The one rule worth repeating here:
compress the bookkeeping, **expand the crux**. Compressing routine enumeration is free;
compressing the one hard inference is where errors get introduced, because the reasoning
that would have caught the mistake is the reasoning you deleted.
