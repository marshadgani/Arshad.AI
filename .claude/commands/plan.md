# /plan

Invoke the Opus-powered planner agent to produce a detailed implementation plan before writing any code.

## Usage
```
/plan <description of what you want to build or fix>
```

## When to Use
Use `/plan` before starting any task that is:
- A new feature touching multiple files or layers
- An architectural decision (new service, new pattern, new dependency)
- Anything with 3+ implementation steps
- Ambiguous in requirements

Skip `/plan` only for trivial single-file changes (config update, rename, one-liner fix).

## What Happens

1. The `planner` agent (Claude Opus) reads the request and all relevant existing code
2. It produces a structured plan with:
   - Design decision and rationale
   - Full list of files to create or modify
   - Ordered, checkable implementation steps
   - Risk assessment
   - Definition of Done
3. You review and approve the plan (or ask for changes)
4. Only after approval does Sonnet begin executing the steps

## Model Split

| Phase | Model | Why |
|---|---|---|
| Planning | `claude-opus-4-7` | Deep reasoning, architectural thinking, catches edge cases |
| Execution | `claude-sonnet-4-6` | Fast, accurate implementation of well-defined steps |

## Example

```
/plan add a POST /sessions endpoint that creates a new conversation session,
      stores it in postgres, and returns the session ID and a welcome message
```

The planner will read the existing `backend/src/` structure, design the
endpoint, migration, and response schema, then output a step-by-step checklist
ready for Sonnet to execute.

## After Planning

Once the plan is approved, execution proceeds step by step:
- Each completed step is checked off in `tasks/todo.md`
- Any deviation from the plan is flagged immediately and re-planned
- Lessons from unexpected issues go into `tasks/lessons.md`
