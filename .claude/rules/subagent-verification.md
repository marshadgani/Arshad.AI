# Subagent Verification Rule

## Why this rule exists

In this Claude Code sandbox, subagents launched via the `Task` tool exhibit a **~95% hallucination rate on file-existence claims**. Both the 117-feature retroactive audit campaign (2026-04-26 to 2026-04-28) and the merge-to-main quality gate (2026-04-28, 3 of 6 agents hallucinated) confirmed this empirically.

Documented in `tasks/handoff.md` and `tasks/lessons.md`.

## The rule

> **Before accepting a subagent claim that any file is missing, empty, deleted, or unchanged, the orchestrator MUST verify with a direct `Read` (or `Bash ls`/`wc -l`) in the main context.**

This applies to:
- Code review subagents claiming "fix not applied"
- Security auditors claiming "files don't exist"
- Doc writers claiming "no comments present"
- Testers claiming "test scripts not in repo"
- Any subagent verdict whose pivot is a *negative existence claim*

## How to apply

When a subagent returns a verdict like:

> "DEF-XXX cannot be confirmed: `path/to/file.py` does not exist"
> "FAIL — no GeneratorExit handler in chat.py"
> "Coverage 0% — no tests found"

**Do NOT propagate the verdict to the user.** Instead:

1. Run `ls -la <path>` and `wc -l <path>` to confirm whether the file actually exists.
2. If it does, `Read` the relevant section to confirm what's actually there.
3. Report manual finding alongside the subagent's hallucinated finding, marked `(manual cross-check)`.
4. In the master gate report, label the subagent verdict explicitly:
   - `HALLUCINATED → manual: PASS` (when verified false and code is fine)
   - `HALLUCINATED → manual: FAIL` (when verified false but code has a different real issue)
   - `CONFIRMED` (when subagent finding holds up under direct inspection)

## What this rule does NOT cover

- **Positive claims** (e.g., "I found a bug at line 42") — still treat with normal scepticism but no automatic cross-check needed; the line number itself is verifiable.
- **Findings within files the subagent did read successfully** (e.g., complexity scores, duplication patterns) — these are subagent strengths.
- **Subagent calls in non-sandbox environments** — this rule is sandbox-specific. Anthropic's production Claude Code does not have this issue.

## Precedent

| Date | Event | Outcome |
|---|---|---|
| 2026-04-27 | Tester subagent claimed "all `backend/src/tools/` files missing" during FEAT-033 audit | Verified false — 12 tool files present. Switched to in-context static review for entire 117-feature campaign. |
| 2026-04-28 | `code-reviewer`, `security-auditor`, `doc-writer` all claimed "files don't exist" during merge-to-main gate | Verified false — `wc -l` confirmed 434+428+129 lines. Cross-verified manually; gate passed. |

## Operational flow

```
                       ┌──────────────────┐
   Subagent verdict ──▶│ Negative claim?  │──▶ no  ──▶ accept normally
                       └────────┬─────────┘
                                │ yes
                                ▼
                       ┌──────────────────┐
                       │ ls/wc/Read the   │
                       │ file directly    │
                       └────────┬─────────┘
                                │
                  ┌─────────────┴─────────────┐
                  ▼                           ▼
             file exists                  truly missing
                  │                           │
                  ▼                           ▼
        manual: cross-check             accept verdict;
        the actual content;             record as CONFIRMED
        relabel HALLUCINATED →
        manual: PASS|FAIL
```

## Removal criteria

Delete this rule when **two consecutive multi-agent runs** show zero file-existence hallucinations. At that point the sandbox limitation has been fixed and the rule is overhead rather than safety.
