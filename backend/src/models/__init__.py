"""SQLAlchemy models. Importing this package registers every model
with ``Base.metadata`` so Alembic autogenerate sees them.
"""

from .database import AsyncSessionLocal, Base, engine, get_db  # noqa: F401
from . import user, oauth_account, oauth_token, dashboard, domain  # noqa: F401, E402
