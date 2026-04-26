"""Calendar tools — register on import.

The router and Phase B chat both consume ``TOOL_REGISTRY`` after this
package is imported. Adding a new calendar tool: write the module,
import it here.
"""

from . import create_event, list_events, update_event  # noqa: F401
