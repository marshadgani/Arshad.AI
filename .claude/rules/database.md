# Database Rules — PostgreSQL + SQLAlchemy (async)

## Models

- Every model inherits from `Base` (defined in `backend/src/models/database.py`).
- Model files live in `backend/src/models/`. One model class per file is preferred for large models.
- Table names are **snake_case plural**: `conversation_messages`, `user_preferences`.
- Column names are **snake_case**.
- Every table has a `created_at` and `updated_at` timestamp, set automatically:
  ```python
  created_at: Mapped[datetime] = mapped_column(default=func.now())
  updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
  ```
- Primary keys use `uuid4` by default — not auto-increment integers.
  ```python
  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  ```

## Queries

- **Always use async sessions** — `AsyncSession` from `sqlalchemy.ext.asyncio`.
- **Never use `session.execute(text(...))` with string interpolation.** Use bound parameters.
  ```python
  # Bad — SQL injection risk
  await session.execute(text(f"SELECT * FROM users WHERE email = '{email}'"))

  # Good
  await session.execute(select(User).where(User.email == email))
  ```
- Prefer the ORM (`select(Model)`) over raw SQL. Use raw SQL only for complex aggregations.
- For queries returning large result sets, always paginate — never fetch unbounded rows.

## Migrations (Alembic)

- **Never edit an existing migration.** Once a migration is committed, it is immutable.
- Generate migrations with: `alembic revision --autogenerate -m "describe_the_change"`
- Review generated migrations before committing — autogenerate sometimes misses things.
- Destructive changes (column removal, table drop) require a two-phase migration:
  1. Phase 1: deprecate (stop writing to the column, deploy)
  2. Phase 2: remove (second migration, deploy after confirming no reads remain)
- Migration files live in `backend/alembic/versions/`.

## Indexes

- Add an index on any column used in a `WHERE` clause in a hot query.
- Add an index on foreign keys — SQLAlchemy does NOT do this automatically.
- Composite indexes: put the highest-cardinality column first.
- Name indexes explicitly: `ix_<table>_<column>`.

## Naming Conventions

| Object | Convention | Example |
|---|---|---|
| Table | snake_case plural | `conversation_messages` |
| Column | snake_case | `created_at` |
| Index | `ix_<table>_<col>` | `ix_messages_session_id` |
| Foreign key | `fk_<table>_<ref_table>` | `fk_messages_sessions` |
| Primary key | `pk_<table>` | `pk_messages` |

## Transactions

- Keep transactions short. Do not hold a transaction open across a network call.
- Use `async with session.begin():` for operations that must be atomic.
- On failure, let exceptions propagate — SQLAlchemy rolls back automatically on context exit.
