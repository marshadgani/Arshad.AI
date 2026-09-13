"""Pass 2 — Pure, byte-deterministic renderers.

``render_entity(row, link_map, user_tail)`` is called once per entity and
returns the full note text: YAML frontmatter (via ``yaml.safe_dump`` —
never string-formatted, so no injection surface) wrapping a managed body
region, followed by verbatim user-authored tail content. Calling this
twice with identical inputs, at any wall-clock time, returns identical
bytes — that's what makes the SHA-diff skip in ``diff.py`` a real no-op
rather than an approximation.

Per-entity-type body rendering is a dispatch table, not an ``if/elif``
chain: a new entity type is a new function plus one registry entry, and
nothing else in this module changes.

``last_synced`` is deliberately never a frontmatter key — see
``models/ontology.py`` docstring on ``last_synced_at``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import yaml

from ....models.ontology import OntologyEntityNote
from .catalogue import INDEX_DOMAIN, INDEX_ENTITY_ID, MOC_TAG, moc_entity_id
from .models import recency_desc_key
from .paths import ONTOLOGY_VAULT_ROOT, note_target

MANAGED_START = "<!-- arshad.ai:managed:start -->"
MANAGED_END = "<!-- arshad.ai:managed:end -->"

# Newest first in MOC listings, and only this many — a MOC is a landing
# page, not an export.
MOC_RECENT_LIMIT = 50

LinkMap = Mapping[str, tuple[str, str]]

_SOURCE_BY_DOMAIN = {
    "calendar": "calendar",
    "email": "gmail",
    "github": "github",
    "people": "derived",
}


# Display names come from third parties (Gmail subjects, calendar event
# titles set by whoever sent the invite, GitHub PR titles). They are
# written into markdown that Obsidian renders, so they are treated as
# untrusted markup, never as text that can be pasted in verbatim:
#   - "<" / ">" would let an attacker-chosen subject inject raw HTML
#     (Obsidian's reader renders inline HTML: <img src=https://evil/…>
#     beacons the vault, <a href> phishes, <iframe> embeds remote content);
#   - "[" / "]" / "|" break out of a "[[target|alias]]" wikilink and let
#     the same string forge links/embeds ("![[…]]") to other notes.
_UNSAFE_INLINE_RE = re.compile(r"[<>\[\]|`]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _inline_text(value: str) -> str:
    """An untrusted display string, made safe to embed in rendered
    markdown. Pure and idempotent — byte-determinism is preserved."""
    cleaned = _CONTROL_RE.sub("", value or "")
    cleaned = _UNSAFE_INLINE_RE.sub("", cleaned)
    return " ".join(cleaned.split()).strip() or "untitled"


class MissingLinkError(Exception):
    """A relationship's target_entity_id has no entry in link_map. This
    is a hard error — a silently-dropped wikilink defeats the entire
    point of the ontology layer, and the resolver already guarantees
    every relationship it keeps IS resolvable, so hitting this means a
    renderer bug, not bad input."""


# ── Primitives ─────────────────────────────────────────────────────


def _wikilink(stable_id: str, link_map: LinkMap) -> str:
    if stable_id not in link_map:
        raise MissingLinkError(stable_id)
    vault_path, display_name = link_map[stable_id]
    # Link by FILENAME, not display name. `slugify_filename` strips
    # characters that are illegal in a path (":" in an email subject is
    # the common case) and `resolve_collision` may append " (2)", so
    # display name and filename routinely differ — a `[[display name]]`
    # link would then dangle, or worse, silently resolve to a DIFFERENT
    # entity's note that happens to own the un-suffixed filename.
    target = _inline_text(note_target(vault_path))
    alias = _inline_text(display_name)
    if target == alias:
        return f"[[{target}]]"
    return f"[[{target}|{alias}]]"


def _link_section(
    title: str, stable_ids: Iterable[str], link_map: LinkMap
) -> list[str]:
    """A ``## title`` heading followed by one wikilink bullet per id, or
    nothing at all when there are no ids."""
    ordered = sorted(stable_ids)
    if not ordered:
        return []
    return ["", f"## {title}", ""] + [
        f"- {_wikilink(sid, link_map)}" for sid in ordered
    ]


def _dataview(where: str) -> str:
    return (
        "```dataview\n"
        "TABLE type, updated\n"
        f'FROM "{ONTOLOGY_VAULT_ROOT}"\n'
        f"WHERE {where}\n"
        "SORT updated DESC\n"
        "```"
    )


def _yaml_block(frontmatter: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        dict(frontmatter),
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
    )


def _note(frontmatter: Mapping[str, Any], body: str, tail: str = "") -> str:
    """The one place the on-disk note layout is defined: frontmatter,
    blank line, managed region, then any user-authored tail."""
    return (
        f"---\n{_yaml_block(frontmatter)}---\n"
        f"\n{MANAGED_START}\n{body}{MANAGED_END}\n{tail}"
    )


def _body(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


# ── Per-entity-type bodies ─────────────────────────────────────────

BodyRenderer = Callable[
    [OntologyEntityNote, LinkMap, Mapping[str, list[str]]], list[str]
]


def _event_body(
    row: OntologyEntityNote, link_map: LinkMap, rels: Mapping[str, list[str]]
) -> list[str]:
    return [f"Calendar event — `{row.stable_entity_id}`."] + _link_section(
        "Attendees", rels.get("attended_by", []), link_map
    )


def _thread_body(
    row: OntologyEntityNote, link_map: LinkMap, rels: Mapping[str, list[str]]
) -> list[str]:
    return [f"Gmail thread — `{row.stable_entity_id}`."] + _link_section(
        "Participants", rels.get("participant", []), link_map
    )


def _repo_body(
    row: OntologyEntityNote, link_map: LinkMap, rels: Mapping[str, list[str]]
) -> list[str]:
    return [f"GitHub repository — `{row.stable_entity_id}`."]


def _issue_pr_body(
    row: OntologyEntityNote, link_map: LinkMap, rels: Mapping[str, list[str]]
) -> list[str]:
    lines = [f"GitHub issue/PR — `{row.stable_entity_id}`."]
    for repo_id in sorted(rels.get("in_repo", [])):
        lines += ["", f"Repo: {_wikilink(repo_id, link_map)}"]
    return lines + _link_section("Author", rels.get("authored_by", []), link_map)


def _person_body(
    row: OntologyEntityNote, link_map: LinkMap, rels: Mapping[str, list[str]]
) -> list[str]:
    return [
        f"Person — `{row.stable_entity_id}`.",
        "",
        "## Related",
        "",
        _dataview("contains(file.outlinks, this.file.link)"),
    ]


def _default_body(
    row: OntologyEntityNote, link_map: LinkMap, rels: Mapping[str, list[str]]
) -> list[str]:
    return [f"`{row.stable_entity_id}`."]


_BODY_RENDERERS: Mapping[str, BodyRenderer] = {
    "Event": _event_body,
    "Thread": _thread_body,
    "Repo": _repo_body,
    "IssuePR": _issue_pr_body,
    "Person": _person_body,
}


def _relationships_by_verb(row: OntologyEntityNote) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for rel in row.relationships or []:
        grouped.setdefault(rel["rel"], []).append(rel["target_entity_id"])
    return grouped


# ── Public renderers ───────────────────────────────────────────────


def render_entity(
    row: OntologyEntityNote,
    link_map: LinkMap,
    user_tail: str | None,
) -> str:
    frontmatter = {
        "uid": row.stable_entity_id,
        "type": row.entity_type,
        "domain": row.domain,
        "source": _SOURCE_BY_DOMAIN.get(row.domain, row.domain),
        "source_id": row.stable_entity_id.split(":", 1)[-1],
        "tags": [f"arshad-ai/{row.domain}", *row.tags],
        "aliases": [],
        "updated": row.source_updated_at.isoformat() if row.source_updated_at else None,
        "status": "active" if row.sync_state != "archived" else "archived",
    }
    render_body = _BODY_RENDERERS.get(row.entity_type, _default_body)
    lines = [f"# {_inline_text(row.display_name)}", ""]
    lines += render_body(row, link_map, _relationships_by_verb(row))
    return _note(frontmatter, _body(lines), user_tail or "")


def extract_user_tail(existing_content: str | None) -> str:
    """The inverse of ``_note``'s tail placement — given the CURRENT bytes
    of a note already in the vault, returns whatever the user appended
    after ``MANAGED_END`` so a re-render can carry it forward unchanged.

    Returns ``""`` when there is nothing to preserve: the note doesn't
    exist yet, or predates the managed-region markers entirely (in which
    case there is no reliable split point and the safest behaviour is to
    treat it as having no recoverable tail rather than guessing).

    Round-trips exactly: ``extract_user_tail(_note(fm, body, tail))``
    reproduces ``tail`` byte-for-byte, which is what lets a merge-then-
    diff pipeline treat "content unchanged" as truly unchanged instead of
    drifting on every sync.
    """
    if not existing_content or MANAGED_END not in existing_content:
        return ""
    after = existing_content.split(MANAGED_END, 1)[1]
    return after[1:] if after.startswith("\n") else after


def render_moc(domain: str, rows: list[OntologyEntityNote], link_map: LinkMap) -> str:
    frontmatter = {
        "uid": moc_entity_id(domain),
        "type": "MOC",
        "domain": domain,
        "tags": [MOC_TAG, f"arshad-ai/{domain}"],
    }
    lines = [
        f"# {domain.title()} — Map of Content",
        "",
        _dataview(f'domain = "{domain}" AND type != "MOC"'),
        "",
        "## Recent",
        "",
    ]
    for row in sorted(rows, key=recency_desc_key)[:MOC_RECENT_LIMIT]:
        lines.append(f"- {_wikilink(row.stable_entity_id, link_map)}")
    return _note(frontmatter, _body(lines))


def render_index(link_map: LinkMap, domains: list[str]) -> str:
    frontmatter = {
        "uid": INDEX_ENTITY_ID,
        "type": "MOC",
        "domain": INDEX_DOMAIN,
        "tags": [MOC_TAG],
    }
    lines = [f"# {ONTOLOGY_VAULT_ROOT} — Index", "", "## Domains", ""]
    for domain in sorted(domains):
        lines.append(f"- {_wikilink(moc_entity_id(domain), link_map)}")
    return _note(frontmatter, _body(lines))
