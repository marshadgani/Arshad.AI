"""SQLAlchemy models. Importing this package registers every model
with ``Base.metadata`` so Alembic autogenerate sees them.
"""

from . import (  # noqa: F401
    ai_ecosystem,
    conversation,
    dag_trigger,
    dashboard,
    domain,
    ingested,
    integration,
    oauth_account,
    oauth_token,
    obsidian,
    skill,
    user,
)
from .base import Base  # noqa: F401 — ensures Base is importable from src.models
