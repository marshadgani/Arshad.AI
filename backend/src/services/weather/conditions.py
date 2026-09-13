"""Wire/cache payload -> current-conditions parsing. Pure.

The upstream body and the Redis entry are both untrusted inputs, and both
are normalised here, so the three tile fields have one named shape instead
of a bare ``dict`` whose keys every consumer has to re-state and defend
against.

No ORM, no HTTP, no Redis, no response schema — this module is importable
and testable on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

_CACHE_FIELDS = ("temp", "condition", "city")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """``value`` if it is a mapping, else an empty one.

    ``x.get(...) or {}`` guards against a *missing* key only. Upstream
    sending a present-but-wrong-typed member (``"main": "n/a"``, or a
    ``weather`` list of bare strings) would still reach ``.get`` and raise
    AttributeError out of a function whose whole job is to absorb exactly
    that.
    """
    return value if isinstance(value, Mapping) else {}


def _as_text(value: Any) -> str | None:
    """A displayable string, or ``None`` for anything that isn't one.

    Every field of this dataclass is annotated ``str | None`` and is handed
    straight to ``WeatherResponse``, whose fields Pydantic v2 validates
    strictly — an ``int`` reaching ``temp`` is a ValidationError, not a
    coercion. Non-strings are therefore dropped to ``None`` (the tile
    degrades per-field, as documented below) rather than passed through to
    fail validation one layer later.

    Blank and whitespace-only strings become ``None`` too: they render as
    an empty slot that looks like a broken widget rather than an absent
    field the card already knows how to omit.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True, slots=True)
class CurrentConditions:
    """What the weather tile renders. Every field is optional: upstream
    omits fields freely and the tile degrades per-field rather than
    failing."""

    temp: str | None = None
    condition: str | None = None
    city: str | None = None

    @classmethod
    def from_upstream(cls, raw: Mapping[str, Any]) -> "CurrentConditions":
        """Parse an OpenWeatherMap ``/weather`` body.

        Metric units are requested upstream, so ``main.temp`` is already
        Celsius; it is rounded and suffixed here rather than in the
        provider so the unit system stays a presentation concern of this
        one tile.
        """
        temp = _as_mapping(raw.get("main")).get("temp")
        # bool is an int subclass: `round(True)` is a cheerful "1 °C".
        numeric = isinstance(temp, (int, float)) and not isinstance(temp, bool)
        entries = raw.get("weather")
        first = entries[0] if isinstance(entries, list) and entries else None
        return cls(
            temp=f"{round(temp)} °C" if numeric else None,
            condition=_as_text(_as_mapping(first).get("main")),
            city=_as_text(raw.get("name")),
        )

    @classmethod
    def from_cache(cls, payload: Mapping[str, Any]) -> "CurrentConditions":
        """Rebuild from a cache entry, reading by key.

        Deliberately not ``cls(**payload)``: an entry written by a
        different parser shape must not raise TypeError here and collapse a
        connected user's tile into the generic degraded state. Unknown keys
        are ignored; missing keys become ``None``.

        Values are normalised by ``_as_text`` for the same reason the keys
        are read individually, and it is not belt-and-braces: reading keys
        defends against a renamed field but not a retyped one, so a stored
        ``{"temp": 15.2}`` (a plausible earlier shape, before the "N °C"
        suffix moved here) still reached ``WeatherResponse`` and failed its
        ``str`` validation. That surfaced as a *degraded* tile which
        re-failed on every request until the 600s TTL expired, because
        nothing on the cache-hit path evicts a poisonous entry.
        """
        return cls(**{f: _as_text(payload.get(f)) for f in _CACHE_FIELDS})

    @property
    def is_renderable(self) -> bool:
        """Whether these conditions are worth showing as a live tile.

        Keyed on ``temp`` because that is what the card keys its live
        branch on (``WeatherCard.tsx``: ``data.degraded || data.temp ==
        null`` renders the unavailable state). A ``CurrentConditions`` with
        no temperature therefore renders identically to a degraded tile,
        which is what makes it worth distinguishing on the cache-hit path.
        """
        return self.temp is not None

    def as_cache_payload(self) -> dict[str, str | None]:
        """The JSON-serialisable form stored in Redis."""
        return asdict(self)
