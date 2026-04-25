# Agent Index — when to use which agent

> Claude: read this when picking an agent. Three pools exist on disk
> (first-party, n8n-mcp, get-shit-done, context7) — they overlap heavily.
> Default to first-party. Only reach for vendored agents when their
> niche clearly fits the task.

## Default routing — task type → agent

| Task | Use | Skip |
|---|---|---|
| Plan a non-trivial task before coding | **`planner`** (first-party, Opus) | `gsd-planner` (needs `/gsd-plan-phase` orchestrator) |
| Review a diff or a PR | **`code-reviewer`** (first-party) | `gsd-code-reviewer` (writes `REVIEW.md`, requires `/gsd-code-review`) |
| Diagnose a bug | **`debugger`** (first-party, scientific method) | `gsd-debugger` (multi-cycle session manager) |
| Run security audit on a diff | **`security-auditor`** (first-party) | `gsd-security-auditor` (verifies threat-model from `PLAN.md`) |
| Write or update docs | **`doc-writer`** (first-party) | `gsd-doc-writer` (needs assignment block) |
| Refactor without changing behaviour | **`refactorer`** (first-party) | none |
| Add tests for new feature | **`test-writer`** (first-party) | `test-automator` (n8n-mcp, broader scope — only for big test infra setup) |
| Look up library / framework docs | **`docs-researcher`** (context7, lightweight) | reading docs inline |
| Set up CI/CD pipeline or containers | **`deployment-engineer`** (n8n-mcp) | first-party (none has this scope) |
| Build or debug an MCP server | **`mcp-backend-engineer`** (n8n-mcp) | first-party |
| Test n8n-mcp specifically | `n8n-mcp-tester` | — |
| Conduct multi-source technical research | **`technical-researcher`** (n8n-mcp) | `docs-researcher` (single-library lookup only) |
| Manage context across long-running multi-agent flow | **`context-manager`** (n8n-mcp) | first-party (none has this) |

## When to use the GSD workflow at all

The 33 `gsd-*` agents implement the **Get Shit Done** methodology — a multi-phase, write-everything-to-disk discipline. They expect orchestration via slash commands (`/gsd-new-project`, `/gsd-plan-phase`, `/gsd-execute-phase`, `/gsd-debug`, `/gsd-secure-phase`, `/gsd-ui-phase`, `/gsd-ai-integration-phase`, `/gsd-code-review`, `/gsd-code-review-fix`, `/gsd-ingest-docs`).

**Do NOT spawn individual gsd-* agents for one-off tasks.** They're stateless from your point of view but they assume `.planning/` files exist (PLAN.md, RESEARCH.md, AI-SPEC.md, etc.).

**Use GSD if** you want a heavyweight, document-driven phase-based workflow where every step writes a structured artifact.

**Skip GSD if** you want a fast, conversational dev loop. The first-party agents + your `/gate` flow already cover this case.

## First-party (7 agents) — primary surface

| Agent | Trigger |
|---|---|
| `planner` | Non-trivial task, 3+ steps, ambiguous approach |
| `code-reviewer` | Reviewing a diff or PR — outputs SHIP / FIX / BLOCK |
| `debugger` | Bug, test failure, unexpected runtime behaviour |
| `security-auditor` | OWASP-style audit, secrets, injection, auth checks |
| `refactorer` | Improve structure / readability without behaviour change; runs tests before & after |
| `test-writer` | Cover happy path + edges + error conditions; pytest or RTL |
| `doc-writer` | Docstrings, JSDoc, README, API ref — never the obvious |

## n8n-mcp (8 agents) — useful niches

| Agent | Trigger |
|---|---|
| `code-reviewer` | (duplicate — prefer first-party) |
| `context-manager` | Coordinating 3+ agents across a long task (10k+ tokens) |
| `debugger` | (duplicate — prefer first-party) |
| `deployment-engineer` | New CI/CD, Dockerfile, Kubernetes, IaC |
| `mcp-backend-engineer` | Anything inside `mcp/` directory or MCP protocol changes |
| `n8n-mcp-tester` | Testing n8n-mcp tool calls specifically — N/A here |
| `technical-researcher` | Multi-source investigation: framework eval, vuln research, API comparison |
| `test-automator` | Greenfield test infrastructure (CI runners, containers, E2E setup) |

## context7 (1 agent)

| Agent | Trigger |
|---|---|
| `docs-researcher` | Single-library doc fetch — keeps main context clean |

## get-shit-done (33 agents) — only when running GSD orchestrators

Listed for reference. Don't invoke individually; they're spawned by the orchestrators below.

| Orchestrator | Spawns |
|---|---|
| `/gsd-new-project` | `gsd-roadmapper`, `gsd-project-researcher`, `gsd-research-synthesizer` |
| `/gsd-plan-phase` | `gsd-planner`, `gsd-phase-researcher`, `gsd-pattern-mapper`, `gsd-plan-checker` |
| `/gsd-execute-phase` | `gsd-executor` |
| `/gsd-code-review` | `gsd-code-reviewer` |
| `/gsd-code-review-fix` | `gsd-code-fixer` |
| `/gsd-debug` | `gsd-debug-session-manager` → `gsd-debugger` |
| `/gsd-secure-phase` | `gsd-security-auditor` |
| `/gsd-ui-phase` | `gsd-ui-researcher`, `gsd-ui-checker` |
| `/gsd-ui-review` | `gsd-ui-auditor` |
| `/gsd-ai-integration-phase` | `gsd-framework-selector`, `gsd-ai-researcher`, `gsd-domain-researcher`, `gsd-eval-planner` |
| `/gsd-eval-review` | `gsd-eval-auditor` |
| `/gsd-ingest-docs` | `gsd-doc-classifier`, `gsd-doc-synthesizer` |
| `/gsd-verify-phase` | `gsd-verifier`, `gsd-integration-checker`, `gsd-nyquist-auditor` |
| `/gsd-map-codebase` | `gsd-codebase-mapper` |
| `/gsd-update-intel` | `gsd-intel-updater` |
| `/gsd-discuss` | `gsd-advisor-researcher`, `gsd-assumptions-analyzer` |
| `/gsd-profile-user` | `gsd-user-profiler` |
| `/gsd-doc-write` | `gsd-doc-writer`, `gsd-doc-verifier` |
| `/gsd-select-framework` | `gsd-framework-selector` |
