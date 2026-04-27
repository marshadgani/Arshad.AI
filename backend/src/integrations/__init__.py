"""Phase G — unified integrations layer.

Importing this package triggers @register decorators across every provider
(personal/* and project/*) so INTEGRATION_REGISTRY is populated by app start.
"""

from . import registry  # noqa: F401
from .personal import github as _p_github  # noqa: F401

# Personal OAuth (wraps existing Phase C OAuth flows)
from .personal import gmail as _p_gmail  # noqa: F401
from .personal import google_calendar as _p_calendar  # noqa: F401

# Bulk providers via factory (Notion, Slack, Todoist, Upstash, Cloudflare,
# Stripe, Sentry, Anthropic, OpenAI, News API)
from .project import bulk_providers as _bulk  # noqa: F401

# Project / infrastructure (API key)
from .project import render as _proj_render  # noqa: F401
from .project import supabase as _proj_supabase  # noqa: F401
from .project import vercel as _proj_vercel  # noqa: F401
