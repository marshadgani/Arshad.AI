# /pr-review

Run a full review of a pull request using the code-reviewer agent.

## Usage
```
/pr-review <pr-number>
```

## Steps

### 1. Fetch the PR
Retrieve the PR title, description, and full diff from GitHub.

### 2. Understand Intent
Read the PR description and linked issue (if any). The reviewer must understand what the PR is trying to do before judging whether it does it correctly.

### 3. Run the code-reviewer Agent
Pass the full diff to the `code-reviewer` agent. It will return structured feedback with severity ratings (🔴 Critical, 🟡 Warning, 🟢 Suggestion).

### 4. Run the security-auditor Agent
Pass the diff to the `security-auditor` agent independently. Security issues are frequently missed in general code review.

### 5. Check Test Coverage
- Every new function should have at least one test.
- Every bug fix should have a regression test.
- If tests are missing, flag them as 🟡 Warning.

### 6. Verify CI Status
Check whether all CI checks are passing. Do not approve a PR with failing checks.

### 7. Post Review
Post the combined review as a GitHub PR comment with this structure:

```
## PR Review — #<number>

### Summary
<What the PR does and overall verdict>

### Critical Issues 🔴
<Must fix before merge>

### Warnings 🟡
<Should fix>

### Suggestions 🟢
<Nice to have>

### Security
<Output from security-auditor, or "No issues found">

### Verdict
[ ] Approve  [x] Request Changes  [ ] Block
```

## Rules
- Never approve a PR with a 🔴 Critical issue.
- Always run both code-reviewer and security-auditor — don't rely on one alone.
- If the PR description is missing or unclear, request that it be filled in before reviewing.
