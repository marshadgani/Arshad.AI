# /pr-review

Full quality gate review — alias for `/gate`. Runs all 6 agents in parallel,
compiles a master gate report, posts it to the PR on GitHub, and presents
a PASS/FAIL/WARN verdict.

## Usage

```
/pr-review           ← reviews open PR for current branch
/pr-review <number>  ← reviews a specific PR by number
```

## Agents Invoked (parallel)

| # | Agent | Gate |
|---|---|---|
| 1 | `code-reviewer` | Bugs, logic errors, performance |
| 2 | `security-auditor` | OWASP, secrets, injection, auth |
| 3 | `debugger` | Runtime failures, unhandled error paths |
| 4 | `test-writer` | Coverage gaps, missing regression tests |
| 5 | `refactorer` | Complexity, duplication, naming |
| 6 | `doc-writer` | Missing docstrings, undocumented APIs |

## Full Protocol

See `.claude/commands/gate.md` for:
- Step-by-step agent orchestration
- Exact gate thresholds (PASS / WARN / FAIL per agent)
- Full report format (posted as PR comment)
- "Merge to Main" auto-merge handler

## Quick Reference

After all agents finish, the gate report is posted to the PR and you see:

```
✅ GATE PASSED   → say "Merge to Main" to merge
⚠️ GATE WARNED   → say "Merge to Main" to merge (warnings non-blocking)
❌ GATE BLOCKED  → fix Critical issues, then re-run /gate
```
