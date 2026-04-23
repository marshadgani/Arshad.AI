# Arshad.AI — Claude Guide

## Project Overview
AI-powered personal assistant with calendar, email, and GitHub integrations. Claude is the AI brain; the backend exposes a chat API that uses tool-calling to take real actions.

## Architecture
```
frontend/   React 18 + TypeScript — chat UI, sidebar with events/emails
backend/    FastAPI — chat endpoint, Claude tool orchestration, REST helpers
postgres    Persistent storage for conversation history and user preferences
redis       Session cache and short-lived tool-call state
```

## Key Conventions
- **Backend**: async everywhere — use `async def` and `await`. Never block the event loop.
- **Frontend**: functional components with hooks only. No class components.
- **Env vars**: never hard-code secrets. Add new vars to `backend/.env.example` when introducing them.
- **AI**: all Claude calls go through `backend/src/services/ai.py`. Tool definitions live in `backend/src/tools/`.

## Running Locally
```bash
cp backend/.env.example backend/.env   # fill in ANTHROPIC_API_KEY
docker compose up --build
```
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Adding a New Tool (Claude integration)
1. Add the tool definition dict to `backend/src/tools/definitions.py`
2. Implement the handler in `backend/src/tools/handlers.py`
3. Register it in the `TOOL_HANDLERS` map

## Environment Variables
| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — required |
| `DATABASE_URL` | Async PostgreSQL DSN |
| `REDIS_URL` | Redis connection string |
| `SECRET_KEY` | App secret for signing sessions |

---

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting work
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what is necessary. Avoid introducing bugs.
