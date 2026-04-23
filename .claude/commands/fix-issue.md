# /fix-issue

Fix a GitHub issue end-to-end: read → plan → implement → test → commit → push.

## Usage
```
/fix-issue <issue-number>
```

## Steps

### 1. Read the Issue
Fetch the issue body and all comments from GitHub. Understand exactly what is broken or requested before writing a single line of code.

### 2. Reproduce (for bugs)
If the issue describes a bug, reproduce it locally before attempting a fix:
```bash
# Run the relevant test or curl the endpoint to confirm the failure
```

### 3. Plan
Write a short plan (3–5 bullet points) describing what you will change and why. Wait for confirmation before implementing if the change is large (>50 lines).

### 4. Implement
Make the minimal change that fixes the issue. Do not bundle unrelated improvements.

- Backend changes: edit files in `backend/src/`
- Frontend changes: edit files in `frontend/src/`
- Database changes: create a new Alembic migration — never edit existing ones

### 5. Write or Update Tests
Every bug fix must include a regression test that would have caught the original bug.
Every feature must include at least a happy-path test.

### 6. Verify
```bash
# Backend
cd backend && python -m pytest tests/ -x -q

# Frontend
cd frontend && npm test -- --watchAll=false
```
All tests must pass before committing.

### 7. Commit and Push
```bash
git add <changed files>
git commit -m "fix: <concise description> (closes #<issue-number>)"
git push -u origin <current-branch>
```

### 8. Report
Summarise what was changed, what test covers it, and link to the commit.
