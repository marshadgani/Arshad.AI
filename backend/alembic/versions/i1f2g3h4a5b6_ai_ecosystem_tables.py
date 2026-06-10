"""ai ecosystem tables

Revision ID: i1f2g3h4a5b6
Revises: h1e2f3a4b5c6
Create Date: 2026-06-10 21:00:00.000000

Adds agent_registry (static agent metadata) and agent_usage_log (per-invocation
metrics). Seeds agent_registry with all 30 dev-team pipeline agents and 8 other
agents. Also inserts the AI Ecosystem nav item.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i1f2g3h4a5b6"
down_revision: Union[str, None] = "h1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Agent seed data — sourced from CLAUDE.md §1 pipeline table
# ---------------------------------------------------------------------------
_SONNET = "claude-sonnet-4-6"
_OPUS = "claude-opus-4-8"
_HAIKU = "claude-haiku-4-5"

_DEV_AGENTS = [
    (
        "code-explorer",
        "Code Explorer",
        "Maps codebase patterns, module boundaries, and naming idioms — context fed to all subsequent agents",
        _SONNET,
        1,
    ),
    (
        "business-analyst",
        "Business Analyst",
        "Extracts requirements and produces a Requirements Traceability Matrix (RTM) and Business Process Design Document",
        _HAIKU,
        2,
    ),
    (
        "enterprise-architect-pre",
        "Enterprise Architect (Pre)",
        "Enterprise architecture review — rejects bad ideas before any code is written",
        _SONNET,
        3,
    ),
    (
        "ai-engineer",
        "AI Engineer",
        "Tech lead — challenges decisions, flags scaling risks, sets architecture direction SA must follow",
        _OPUS,
        4,
    ),
    (
        "solution-architect",
        "Solution Architect",
        "Produces Solution Design Document (SDD) constrained by Tech Lead direction",
        _SONNET,
        5,
    ),
    (
        "architecture-critic",
        "Architecture Critic",
        "Adversarially reviews the SDD — flags over-engineering, coupling risks, and convention deviations",
        _OPUS,
        6,
    ),
    (
        "system-engineer",
        "System Engineer",
        "Designs system architecture, component structure, data flow, DB schema, and caching strategy",
        _OPUS,
        7,
    ),
    (
        "engineer",
        "Engineer",
        "Builds production-ready MVP from SDD and system design",
        _SONNET,
        8,
    ),
    (
        "developer",
        "Developer",
        "Generates complete feature code from the Solution Design Document",
        _SONNET,
        9,
    ),
    (
        "database-specialist",
        "Database Specialist",
        "Deep SQL/ORM/migration audit — N+1, missing indexes, unsafe queries, Alembic correctness",
        _SONNET,
        10,
    ),
    (
        "python-specialist",
        "Python Specialist",
        "Python/FastAPI audit — async correctness, Pydantic v2, dependency injection, type annotations",
        _SONNET,
        11,
    ),
    (
        "code-reviewer",
        "Code Reviewer",
        "Project-conventions review against CLAUDE.md rules for API, database, and frontend patterns",
        _OPUS,
        12,
    ),
    (
        "frontend-engineer",
        "Frontend Engineer",
        "Production-grade UI with bold aesthetic direction — all 4 states, accessible, responsive, reusable",
        _SONNET,
        13,
    ),
    (
        "type-design-analyzer",
        "Type Design Analyzer",
        "TypeScript type system audit — weak types, missing invariant encoding, illegal-state prevention",
        _SONNET,
        14,
    ),
    (
        "senior-engineer",
        "Senior Engineer",
        "Code quality audit — finds N+1, bad patterns, scalability risks. No functionality changes.",
        _OPUS,
        15,
    ),
    (
        "software-architect",
        "Software Architect",
        "Architecture restructuring — separates concerns, reduces coupling, increases modularity",
        _OPUS,
        16,
    ),
    (
        "silent-failure-hunter",
        "Silent Failure Hunter",
        "Error handling audit — swallowed exceptions, HTTP 200 masking errors, missing propagation",
        _SONNET,
        17,
    ),
    (
        "code-simplifier",
        "Code Simplifier",
        "Code clarity refinement — eliminates unnecessary abstraction, over-engineering, verbose constructs",
        _OPUS,
        18,
    ),
    (
        "process-organiser",
        "Process Organiser",
        "Logs the feature in the process hierarchy for project tracking",
        _HAIKU,
        19,
    ),
    (
        "test-architect",
        "Test Architect",
        "Designs test architecture — unit vs integration boundaries, mock strategy, coverage plan",
        _SONNET,
        20,
    ),
    (
        "test-script-writer",
        "Test Script Writer",
        "Writes deterministic test scripts covering every acceptance criterion in the RTM plus edge cases",
        _SONNET,
        21,
    ),
    (
        "pr-test-analyzer",
        "PR Test Analyzer",
        "Test quality review — coverage of happy/error/edge paths, negative tests, behaviour vs implementation",
        _SONNET,
        22,
    ),
    (
        "tester",
        "Tester",
        "Executes tests against the feature code and reports defects with root cause analysis",
        _SONNET,
        23,
    ),
    (
        "bug-fixer",
        "Bug Fixer",
        "Fixes defects found by the Tester and prepares code for re-test (max 5 iterations)",
        _SONNET,
        24,
    ),
    (
        "debugger",
        "Debugger",
        "Root cause analysis — production outage mode, traces failures 3 levels deep",
        _OPUS,
        25,
    ),
    (
        "performance-optimizer",
        "Performance Optimizer",
        "Eliminates bottlenecks — N+1, missing indexes, async gaps, memory leaks",
        _SONNET,
        26,
    ),
    (
        "security-auditor",
        "Security Auditor",
        "OWASP Top 10 — attack scenarios, injection, auth flaws, secure implementation fixes",
        _OPUS,
        27,
    ),
    (
        "devops-engineer",
        "DevOps Engineer",
        "Deployment architecture, monitoring, scaling, and production deployment checklist",
        _SONNET,
        28,
    ),
    (
        "production-validator",
        "Production Validator",
        "Final production-readiness check — no stubs, no TODOs, all endpoints functional, no debug code",
        _SONNET,
        29,
    ),
    (
        "enterprise-architect-post",
        "Enterprise Architect (Post)",
        "Final architectural verdict — reviews completed code against BPDD and SDD for alignment",
        _SONNET,
        30,
    ),
]

_OTHER_AGENTS = [
    (
        "planner",
        "Planner",
        "Strategic planning and task orchestration — breaks down complex objectives into executable steps",
        _OPUS,
    ),
    (
        "doc-writer",
        "Doc Writer",
        "Writes docstrings, README sections, API references, and inline comments for human readers",
        _SONNET,
    ),
    (
        "refactorer",
        "Refactorer",
        "Improves code structure and readability without changing observable behaviour — runs tests before and after",
        _SONNET,
    ),
    (
        "test-writer",
        "Test Writer",
        "Writes unit and integration tests for Python and TypeScript — happy paths, edge cases, error conditions",
        _SONNET,
    ),
    (
        "orchestrator",
        "Orchestrator",
        "General-purpose planner and executor — plans task graphs across specialist agents and synthesises results",
        _OPUS,
    ),
    (
        "code-explorer",
        "Code Explorer",
        "Deeply analyses existing codebase features by tracing execution paths and mapping architecture layers",
        _SONNET,
    ),
    (
        "brainstorming",
        "Brainstorming",
        "Explores user intent, requirements, and design options before any implementation begins",
        _SONNET,
    ),
    (
        "gate-runner",
        "Gate Runner",
        "Runs the 8-agent quality gate before any merge to main — compiles the master report and posts to PR",
        _SONNET,
    ),
]


def upgrade() -> None:
    # ── agent_registry ──────────────────────────────────────────────────────
    op.create_table(
        "agent_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("pipeline_stage", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_registry"),
        sa.UniqueConstraint("agent_name", name="uq_agent_registry_agent_name"),
    )
    op.create_index("ix_agent_registry_agent_name", "agent_registry", ["agent_name"])

    # ── agent_usage_log ─────────────────────────────────────────────────────
    op.create_table(
        "agent_usage_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "invoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_usage_log"),
    )
    op.create_index("ix_agent_usage_log_agent_name", "agent_usage_log", ["agent_name"])
    op.create_index("ix_agent_usage_log_invoked_at", "agent_usage_log", ["invoked_at"])

    # ── seed agent_registry ─────────────────────────────────────────────────
    conn = op.get_bind()

    import uuid as _uuid

    for agent_name, display_name, purpose, model, stage in _DEV_AGENTS:
        conn.execute(
            sa.text(
                "INSERT INTO agent_registry "
                "(id, agent_name, display_name, purpose, model, category, pipeline_stage, is_active) "
                "VALUES (:id, :agent_name, :display_name, :purpose, :model, :category, :stage, true) "
                "ON CONFLICT (agent_name) DO NOTHING"
            ),
            {
                "id": str(_uuid.uuid4()),
                "agent_name": agent_name,
                "display_name": display_name,
                "purpose": purpose,
                "model": model,
                "category": "development_team",
                "stage": stage,
            },
        )

    for agent_name, display_name, purpose, model in _OTHER_AGENTS:
        conn.execute(
            sa.text(
                "INSERT INTO agent_registry "
                "(id, agent_name, display_name, purpose, model, category, pipeline_stage, is_active) "
                "VALUES (:id, :agent_name, :display_name, :purpose, :model, :category, NULL, true) "
                "ON CONFLICT (agent_name) DO NOTHING"
            ),
            {
                "id": str(_uuid.uuid4()),
                "agent_name": agent_name,
                "display_name": display_name,
                "purpose": purpose,
                "model": model,
                "category": "other",
            },
        )

    # ── nav_items: AI Ecosystem tab ─────────────────────────────────────────
    conn.execute(
        sa.text(
            "INSERT INTO nav_items (path, label, icon, domain, ord) "
            "VALUES (:path, :label, :icon, :domain, :ord) "
            "ON CONFLICT (path) DO UPDATE SET label = EXCLUDED.label, icon = EXCLUDED.icon, ord = EXCLUDED.ord"
        ),
        {
            "path": "/ai-ecosystem",
            "label": "AI Ecosystem",
            "icon": "🤖",
            "domain": None,
            "ord": 8,
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM nav_items WHERE path = '/ai-ecosystem'"))
    op.drop_index("ix_agent_usage_log_invoked_at", table_name="agent_usage_log")
    op.drop_index("ix_agent_usage_log_agent_name", table_name="agent_usage_log")
    op.drop_table("agent_usage_log")
    op.drop_index("ix_agent_registry_agent_name", table_name="agent_registry")
    op.drop_table("agent_registry")
