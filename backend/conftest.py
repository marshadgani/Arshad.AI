import os
import sys

# Provide required env vars before any app module imports trigger startup
# validation. The values are fake — no actual connections are made in unit
# tests that don't exercise DB/Redis paths.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars-x")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

# Allow `from src.xxx import ...` when pytest is run from backend/.
sys.path.insert(0, os.path.dirname(__file__))
