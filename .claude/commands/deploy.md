# /deploy

Run pre-deployment checks and deploy the application.

## Usage
```
/deploy [staging|production]
```
Defaults to `staging` if no environment is specified.

## Pre-Deploy Checklist

### 1. Type Check
```bash
cd frontend && npx tsc --noEmit
```
Must exit 0. Fix all type errors before continuing.

### 2. Lint
```bash
cd frontend && npx eslint src/ --max-warnings 0
cd backend  && ruff check src/
```

### 3. Tests
```bash
cd backend  && python -m pytest tests/ -x -q
cd frontend && npm test -- --watchAll=false --passWithNoTests
```
All tests must pass. No skipping.

### 4. Secrets Scan
```bash
git diff HEAD~1 | grep -iE "(api_key|secret|password|token)\s*=" && echo "SECRETS FOUND — ABORT" || echo "clean"
```
Abort if any secrets are detected in the diff.

### 5. Dependency Audit
```bash
cd backend  && pip-audit -r requirements.txt
cd frontend && npm audit --audit-level=high
```
Block on any high or critical CVEs.

### 6. Environment Check
Confirm the target environment's `.env` has:
- `ANTHROPIC_API_KEY` set (non-empty, non-placeholder)
- `SECRET_KEY` is not `change-me`
- `DATABASE_URL` points to the correct host

## Deploy

### Staging
```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build
```

### Production
```bash
# Production deploy requires explicit confirmation
echo "Deploying to PRODUCTION — confirm? (yes/no)"
# Wait for yes before proceeding
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## Post-Deploy Verification
```bash
curl -f http://<host>:8000/health && echo "Backend OK"
curl -f http://<host>:3000        && echo "Frontend OK"
```

If either check fails, roll back immediately:
```bash
docker compose down && docker compose up -d  # restores previous image
```
