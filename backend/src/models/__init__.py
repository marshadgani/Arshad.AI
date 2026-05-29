"""SQLAlchemy models. Importing this package registers every model
with ``Base.metadata`` so Alembic autogenerate sees them.
"""

from .database import AsyncSessionLocal, Base, engine, get_db  # noqa: F401
from . import dashboard, domain, oauth_account, oauth_token, user  # noqa: F401
