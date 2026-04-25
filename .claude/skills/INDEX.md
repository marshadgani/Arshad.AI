# Skill Index — what's available and when to invoke

> Claude: read this file when planning a task. Skills auto-surfaced via
> `Skill` tool may be a small subset of what's on disk. For a skill that
> isn't surfaced, you can still **read** the SKILL.md at the path below
> and apply its workflow.

## Routing — task type → preferred skill

| Task type | First choice | Path |
|---|---|---|
| Plan a multi-step task | `plan` (slash command) | — |
| Brainstorm before writing code | `superpowers/brainstorming` | `superpowers/brainstorming/SKILL.md` |
| Write an implementation plan from a spec | `superpowers/writing-plans` | `superpowers/writing-plans/SKILL.md` |
| Execute a written plan | `superpowers/executing-plans` | `superpowers/executing-plans/SKILL.md` |
| Debug a bug or unexpected behaviour | `superpowers/systematic-debugging` | `superpowers/systematic-debugging/SKILL.md` |
| Add a feature or fix → enforce TDD | `superpowers/test-driven-development` | `superpowers/test-driven-development/SKILL.md` |
| Verify before claiming done | `superpowers/verification-before-completion` | `superpowers/verification-before-completion/SKILL.md` |
| Code review (request) | `superpowers/requesting-code-review` | `superpowers/requesting-code-review/SKILL.md` |
| Code review (receive feedback) | `superpowers/receiving-code-review` | `superpowers/receiving-code-review/SKILL.md` |
| Finish + integrate a branch | `superpowers/finishing-a-development-branch` | `superpowers/finishing-a-development-branch/SKILL.md` |
| Parallel sub-tasks | `superpowers/dispatching-parallel-agents` | `superpowers/dispatching-parallel-agents/SKILL.md` |
| Anthropic SDK / Claude API code | `everything-claude-code/claude-api` | `everything-claude-code/claude-api/SKILL.md` (or top-level `claude-api`) |
| Build an MCP server | `everything-claude-code/mcp-server-patterns` | `everything-claude-code/mcp-server-patterns/SKILL.md` |
| Look up library / framework docs | `context7` (auto-surfaced) | `context7/find-docs/SKILL.md` |
| New REST API endpoint | `everything-claude-code/api-design` | `everything-claude-code/api-design/SKILL.md` |
| Backend FastAPI / Node patterns | `everything-claude-code/backend-patterns` | `everything-claude-code/backend-patterns/SKILL.md` |
| New React component / page | `everything-claude-code/frontend-design` (or `frontend-patterns`) | `everything-claude-code/frontend-design/SKILL.md` |
| E2E test setup (Playwright) | `everything-claude-code/e2e-testing` | `everything-claude-code/e2e-testing/SKILL.md` |
| Eval-driven AI development | `everything-claude-code/eval-harness` | `everything-claude-code/eval-harness/SKILL.md` |
| Add auth / handle secrets / sensitive code | `everything-claude-code/security-review` | `everything-claude-code/security-review/SKILL.md` |
| UI styling (Tailwind + shadcn) | `ui-ux-pro-max-skill/ui-styling` | `ui-ux-pro-max-skill/ui-styling/SKILL.md` |
| Design system tokens | `ui-ux-pro-max-skill/design-system` | `ui-ux-pro-max-skill/design-system/SKILL.md` |

## Inventory by source

### `superpowers/` (13 skills) — workflow discipline
- `brainstorming` · `dispatching-parallel-agents` · `executing-plans` · `finishing-a-development-branch` · `receiving-code-review` · `requesting-code-review` · `subagent-driven-development` · `systematic-debugging` · `test-driven-development` · `using-git-worktrees` · `using-superpowers` · `verification-before-completion` · `writing-plans` · `writing-skills`

### `everything-claude-code/` (34 skills) — broad library
**Project-relevant (likely to be invoked here):**
- `claude-api` · `mcp-server-patterns` · `documentation-lookup` · `coding-standards` · `api-design` · `backend-patterns` · `frontend-design` · `frontend-patterns` · `tdd-workflow` · `e2e-testing` · `eval-harness` · `security-review` · `verification-loop` · `strategic-compact` · `agent-introspection-debugging` · `product-capability` · `deep-research`

**Stack-specific (not used in this stack — Bun/Next):**
- `bun-runtime` · `nextjs-turbopack`

**Content / GTM (probably not used by this project):**
- `article-writing` · `brand-voice` · `content-engine` · `crosspost` · `frontend-slides` · `investor-materials` · `investor-outreach` · `market-research` · `video-editing` · `x-api`

**Tooling-specific:**
- `dmux-workflows` · `exa-search` · `fal-ai-media` · `agent-sort` · `everything-claude-code` (meta)

### `context7/` (3 skills) — library doc lookup
- `context7-cli` · `context7-mcp` · `find-docs`

### `ui-ux-pro-max-skill/` (7 skills) — design + UI work
- `banner-design` · `brand` · `design` · `design-system` · `slides` · `ui-styling` · `ui-ux-pro-max`

### `claude-mem/` (7 skills) — memory + planning (requires claude-mem CLI)
- `do` · `knowledge-agent` · `make-plan` · `mem-search` · `smart-explore` · `timeline-report` · `version-bump`

### `obsidian-skills/` (5 skills) — Obsidian vault integration
- `defuddle` · `json-canvas` · `obsidian-bases` · `obsidian-cli` · `obsidian-markdown`

## Discoverability note

Most of these live two levels deep (`<source>/<skill>/SKILL.md`) and are NOT auto-surfaced by Claude Code's `Skill` tool. To use one that isn't surfaced:

1. Read the SKILL.md at the path above with the `Read` tool.
2. Apply the workflow described in it.
3. The skill content is a structured prompt — treat it as a guide.

To **promote** a frequently-used skill to top-level discoverability, copy or symlink its directory into `.claude/skills/<name>/` (next to this index).
