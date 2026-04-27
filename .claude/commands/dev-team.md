# /dev-team

Orchestrates the 9-agent dev pipeline that turns a feature requirement into structured artifacts + tested code on a fresh git branch.

## Usage

```
/dev-team <feature requirement>
```

Or auto-triggered per CLAUDE.md §21 when a user prompt classifies as a feature requirement.

## Cost model

All agent invocations are `Task()` calls within this Claude Code session. **Zero `ANTHROPIC_API_KEY` consumption.** Same billing model as every other agent in `.claude/agents/`.

## Pipeline sequence

When this command runs, you (Claude Code) follow this exact recipe:

### Step 0 — Confirm + issue feature ID

1. Reflect interpretation back to user, ask for one-word confirmation.
2. On confirmation, read `tasks/.feature-counter`, increment, write back atomically:
   ```bash
   N=$(cat tasks/.feature-counter); NEW=$((N+1)); echo "$NEW" > tasks/.feature-counter.tmp && mv tasks/.feature-counter.tmp tasks/.feature-counter
   FEAT_ID=$(printf "FEAT-%03d" "$NEW")
   ```
3. Capture start timestamp (ISO 8601 UTC, e.g., `2026-04-26T23:45:00Z`).

### Step 1 — Business Analyst

```
Task(subagent_type="business-analyst", description="Extract RTM + BPDD",
     prompt=f"Feature ID: {FEAT_ID}\n\nRequirement:\n{requirement}")
```

Parse the JSON output. Validate it has `rtm` and `bpdd` keys. Write to:
`tasks/agent-outputs/ba/{FEAT_ID}_{timestamp}.json`

Capture: `bpdd.feature_name`, `bpdd.domain`, `bpdd.sub_section`.

### Step 2 — Enterprise Architect (pre-build)

```
Task(subagent_type="enterprise-architect", description="EA pre-build review",
     prompt=f"Feature ID: {FEAT_ID}\nStage: pre_build\n\nBPDD:\n{json.dumps(bpdd, indent=2)}")
```

Write to `tasks/agent-outputs/ea/{FEAT_ID}_pre_{timestamp}.json`.

If `decision == "rejected"`, halt the pipeline. Log the row to `tasks/pipeline-runs.md` with status `halted`. Stop.

### Step 3 — Solution Architect

```
Task(subagent_type="solution-architect", description="Produce SDD",
     prompt=f"Feature ID: {FEAT_ID}\n\nBPDD:\n{json.dumps(bpdd, indent=2)}")
```

Write to `tasks/agent-outputs/sa/{FEAT_ID}_{timestamp}.json`.

### Step 4 — Developer

```
Task(subagent_type="developer", description="Generate feature code",
     prompt=f"Feature ID: {FEAT_ID}\n\nSDD:\n{json.dumps(sdd, indent=2)}")
```

Write to `tasks/agent-outputs/dev/{FEAT_ID}_{timestamp}.json` (the JSON record itself).

**Then validate every `path` in `files[]` against the denylist:**
- `backend/src/main.py`, `backend/src/auth/*`
- `backend/alembic/env.py`, existing `backend/alembic/versions/*`
- `.github/workflows/*`, `render.yaml`, `vercel.json`, `Dockerfile*`
- `CLAUDE.md`, `tasks/process-hierarchy.md`, `tasks/last-gate-report.md`, `tasks/lessons.md`, `tasks/.feature-counter`
- Any path with `..` or absolute paths

If ANY path is forbidden, halt the pipeline (do not write files yet).

### Step 5 — Process Organiser

```
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
Task(subagent_type="process-organiser", description="Confirm PHD entry",
     prompt=f"Feature ID: {FEAT_ID}\nFeature name: {feature_name}\nDomain: {domain}\nSub-section: {sub_section}\nTimestamp: {TIMESTAMP}")
```

Write to `tasks/agent-outputs/po/{FEAT_ID}_{timestamp}.json`.

If `entry.feature_name` starts with `"WARNING:"`, halt the pipeline.

Otherwise, atomically append to `tasks/process-hierarchy.md`:

```bash
# Read current PHD, parse, append, write atomically.
# Format:
#   Domain: <Domain>
#   Sub-section: <Sub-section>
#   [FEAT-NNN] <Feature name> — added <ISO timestamp>
#
# Algorithm: read file, find/insert the right Domain block, find/insert
# the right Sub-section block, append the entry line, write to .tmp, mv.
```

Use the Edit tool on `tasks/process-hierarchy.md` if structure already has the right Domain+Sub-section, otherwise Write the full new file via tmp+mv pattern.

### Step 6 — Test Script Writer

```
Task(subagent_type="test-script-writer", description="Write test scripts",
     prompt=f"Feature ID: {FEAT_ID}\n\nBPDD:\n{json.dumps(bpdd)}\n\nSDD:\n{json.dumps(sdd)}")
```

Write to `tasks/agent-outputs/tsw/{FEAT_ID}_{timestamp}.json`.

### Step 7 — Tester (iteration 0)

```
Task(subagent_type="tester", description="Test code (iter 0)",
     prompt=f"Feature ID: {FEAT_ID}\nIteration: 0\n\nTest scripts:\n{json.dumps(scripts)}\n\nCode under test:\n{format_code_block(code)}")
```

Write to `tasks/agent-outputs/tester/{FEAT_ID}_run0_{timestamp}.json`.

### Step 8 — Bug-fix loop (max 5 iterations)

```
iteration = 0
while catalogue.defects:
    iteration += 1
    if iteration > 5:
        halt_reason = "unresolved defects after 5 bug-fix iterations"
        break
    Task(subagent_type="bug-fixer", description=f"Fix defects (iter {iteration})",
         prompt=f"Feature ID: {FEAT_ID}\nIteration: {iteration}\n\nCatalogue:\n{json.dumps(catalogue)}\n\nCode:\n{format_code_block(code)}")
    # → write tasks/agent-outputs/bugfixer/{FEAT_ID}_iter{iteration}_{ts}.json
    # → re-validate path denylist
    code = output.fixed_code

    Task(subagent_type="tester", description=f"Test code (iter {iteration})",
         prompt=...)
    # → write tasks/agent-outputs/tester/{FEAT_ID}_run{iteration}_{ts}.json
    catalogue = new_catalogue
```

### Step 9 — Enterprise Architect (post-build) — ALWAYS RUNS

Even if Step 8 halted on the iteration cap, this step runs.

```
Task(subagent_type="enterprise-architect", description="EA post-build review",
     prompt=f"Feature ID: {FEAT_ID}\nStage: post_build\n\nBPDD:\n{json.dumps(bpdd)}\n\nSDD:\n{json.dumps(sdd)}\n\nCode summary: {code.summary}\nFiles: {[f.path for f in code.files]}")
```

Write to `tasks/agent-outputs/ea/{FEAT_ID}_post_{timestamp}.json`.

### Step 10 — Branch + commit

**Branch slug sanitization (mandatory):** the slug derives from the user's requirement string, which is untrusted input. Strip everything except `[a-z0-9-]`, cap at 50 chars, NEVER pass unquoted to `git`.

```bash
# Sanitize: lowercase → keep only [a-z0-9] + collapse other chars to '-' → trim
# leading/trailing hyphens → cap at 50 chars
SLUG=$(printf '%s' "$REQUIREMENT" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed -e 's/^-*//' -e 's/-*$//' | cut -c1-50)
# Refuse empty/all-symbol slugs (would create branch "dev-team/feat-001-")
[ -z "$SLUG" ] && SLUG="feature"
# Validate FEAT_ID format defensively (must match FEAT-NNN)
[[ "$FEAT_ID" =~ ^FEAT-[0-9]+$ ]] || { echo "Invalid FEAT_ID: $FEAT_ID"; exit 1; }
BRANCH="dev-team/${FEAT_ID,,}-${SLUG}"
git checkout -b "$BRANCH" --   # `--` ends option parsing, prevents flag injection
# Write each file in code.files via Write tool, then:
git add .
git commit -m "feat($FEAT_ID): $code_summary

Generated by dev-team pipeline.

Files:
$(printf -- '- %s\n' "${code.files[@]}")"
```

### Step 11 — Log + report

Append one row to `tasks/pipeline-runs.md`:

```
| <started> | FEAT-NNN | <requirement_truncated> | completed | <bug_fix_iters> | <ea_post_decision> | <duration>s |
```

Report back to user:
- Feature ID
- Branch name
- Bug-fix iterations
- EA post-build decision
- Path to each artifact

## Halt conditions

- EA pre-build returns `rejected` → halt at step 2
- Developer returns a forbidden path → halt at step 4
- Process Organiser returns `WARNING:` prefix → halt at step 5
- Bug-fix loop hits 5 iterations → halt before step 9 BUT step 9 (EA post-build) STILL RUNS to capture the final state

In all halt cases, log the row with status `halted` and the halt reason.

## What you do NOT do

- No direct Anthropic SDK calls. Every "agent" is a `Task()` subagent.
- No background processes. Pipeline runs synchronously in this conversation.
- No writes to paths in the denylist.
- No edits to `develop-AION` or `main` directly. Always a `dev-team/<feat-id>-<slug>` branch.
- No re-issuing the same FEAT-NNN. The counter is monotonic.
