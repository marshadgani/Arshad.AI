# /session-end

Close out a session: write a handoff for next time, append a dev log entry, optionally push.

## Usage
```
/session-end
```

No arguments. The command reads the current repo state and conversation context.

## Why this exists

`tasks/handoff.md` is the single "where we are right now" snapshot — overwritten every session, read by the SessionStart hook so the next session starts in flow within seconds. `tasks/dev-log.md` is append-only history — the durable record of decisions, pivots, and skipped work that becomes the project's living documentation.

The push step is **opt-in** (private by default) so a session can end without leaving the working branch in a state you didn't approve.

## Steps

### 1. Survey

Run these in parallel before writing anything:

```bash
git status --short
git log --oneline origin/claude/ai-personal-assistant-main..HEAD
git diff --stat origin/claude/ai-personal-assistant-main..HEAD | tail -5
git rev-parse --abbrev-ref HEAD
git rev-parse --short HEAD
```

Also scan the conversation for: what the user asked for, what got built, what was deliberately skipped, any locked decisions, and any unresolved questions.

### 2. Overwrite `tasks/handoff.md`

This file is the next session's first read. Keep it tight — under 60 lines. Use this exact structure:

```markdown
# Handoff — <today's date>

**Branch:** <branch>
**HEAD:** <short SHA> · <one-line subject>
**Last gate:** <PASSED|WARN|BLOCKED — link to last-gate-report.md commit>

## Where we are
- 3-5 bullets summarising the project's current state. Lead with the BIG thing
  that just shipped or is in flight. Mention which phase / feature / branch
  is active.

## What's next
- 3-5 bullets of the immediate next moves, ordered by what should happen first.
  Each bullet starts with a verb. If a decision is needed before action, say so.

## Watch out for
- 1-3 bullets of hidden traps for the next session: half-applied configs,
  squash-divergence states, env vars that need setting, deploy steps the user
  has to do manually, CI quirks. Things future-Claude will trip over without
  the context.

## Open questions
- (optional) Anything the user said "we'll decide later" about. Skip the
  section if there's nothing.
```

Always overwrite this file fully — never append. The whole point is that it stays small.

### 3. Append to `tasks/dev-log.md`

This is append-only. Insert a new entry at the **top** of the file (newest first), under the existing header. Format:

```markdown
## <YYYY-MM-DD> — <short topic>

**HEAD at end of session:** `<short SHA>`
**Branch:** `<branch>`
**Started from handoff:** `<short SHA of the handoff commit this session was resumed from>` — see `git log tasks/handoff.md` to walk the chain backward.

### Built
- Bullets of what shipped this session. Cite commit SHAs where useful.

### Skipped (with rationale)
- Bullets of what was explicitly NOT done and why. Skip the section if nothing
  was skipped.

### Decisions
- Locked-in decisions made this session. Quote the user's choice when relevant
  (e.g. "1a, 2b, 3a, 4a, 5c — 24 agents, deterministic dispatchers..."). These
  become the project's contract going forward.

### Lessons / corrections
- (optional) Mistakes the user caught + the rule going forward. Cross-reference
  any tasks/lessons.md entries added.

---
```

The `---` separator goes between entries.

**Why "Started from handoff":** every dev-log entry forms one link in a backward-walkable chain. Future-you can reconstruct any past state by following `Started from handoff` → that commit → its handoff content → its referenced "Started from" → and so on. The chain is the project's git-native equivalent of a session journal.

To find the prior handoff SHA at the start of step 3:
```bash
git log -1 --format='%h' tasks/handoff.md
```
That's the SHA of the handoff commit Claude Code resumed from at session start (before this session's overwrite).

### 4. Commit

Single commit covering both files:

```bash
git add tasks/handoff.md tasks/dev-log.md
git commit -m "chore(session): handoff + dev log entry — <short topic>

<one paragraph: what shipped, what was decided, what's queued for next time>

https://claude.ai/code/session_<id>"
```

Do **NOT** push yet. The next step asks the user.

### 5. Ask about push (private by default)

Use **AskUserQuestion** with this exact shape:

> **Push handoff + dev log to origin?**
> - **(a)** Yes — push to the current branch.
> - **(b)** No — keep the commit local. (default)

Default is **no**. The user explicitly opts in. If yes, run:

```bash
git push origin "$(git branch --show-current)"
```

If the push triggers the auto-pr workflow's gate-merge cycle, note that to the user.

### 6. Final report

Output to the user:
- Handoff file path + first 3 lines.
- Dev log entry header (the `## YYYY-MM-DD — topic` line).
- Whether the commit pushed or stayed local.

Done.

## Conventions

- **Always commit, never just write.** A handoff that isn't in git is a handoff that's gone.
- **Never edit past dev log entries.** They're a historical record. If a previous decision was wrong, write a new entry that corrects it.
- **Keep handoff.md under 60 lines.** Tight is the whole point.
- **Don't include secrets, tokens, or full env values in either file.** Branch names, file paths, SHAs only.
- **Always cite "Started from handoff: <SHA>" in dev-log entries.** This is the chain link that lets `git log tasks/handoff.md` reconstruct any past project state. A dev-log entry without this field is a snapped link.
