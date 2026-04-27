"""Phase G — unified integrations layer.

Importing this package triggers @register decorators across every provider
(personal/* and project/*) so INTEGRATION_REGISTRY is populated by app start.
"""

# Coming-soon stubs (OAuth-only providers + no-API services)
from . import coming_soon as _coming_soon  # noqa: F401
from . import registry  # noqa: F401

# Personal OAuth (wraps existing Phase C OAuth flows + Google sub-services)
from .personal import github as _p_github  # noqa: F401
from .personal import gmail as _p_gmail  # noqa: F401
from .personal import google_calendar as _p_calendar  # noqa: F401
from .personal import google_drive as _p_drive  # noqa: F401
from .personal import google_tasks as _p_tasks  # noqa: F401
from .personal import openweathermap as _p_owm  # noqa: F401

# Static (no-credentials): Hacker News, Open-Meteo
from .personal import static_providers as _p_static  # noqa: F401

# Bulk providers via factory (Notion, Slack, Todoist, Upstash, Cloudflare,
# Stripe, Sentry, Anthropic, OpenAI, News API)
from .project import bulk_providers as _bulk  # noqa: F401

# Project / infrastructure (API key)
from .project import render as _proj_render  # noqa: F401
from .project import supabase as _proj_supabase  # noqa: F401
from .project import vercel as _proj_vercel  # noqa: F401
