"""Atomic read / parse / append / render / write for tasks/process-hierarchy.md.

The Process Organiser agent calls update_phd() after every successful
pipeline run. Constraints (per spec):
  - Single file. Never recreated, never replaced.
  - Entries are append-only — never removed or rewritten in place.
  - File header is preserved verbatim.
  - Crash mid-write must leave the original file intact (atomic rename).

Format:
    Domain: <Domain>
    Sub-section: <Sub-section>
    [FEAT-NNN] <Feature name> — added <ISO timestamp>

Multiple sub-sections under one domain stack as:
    Domain: User Management
    Sub-section: Authentication
    [FEAT-001] ...
    [FEAT-002] ...
    Sub-section: Authorization
    [FEAT-003] ...

The parser is forgiving: ignores blank lines, preserves the file header
above the entry block, sorts entries by feature_id within each
sub-section.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from pathlib import Path

from .artifacts import PHEntry
from .storage import repo_root

_PHD_PATH = "tasks/process-hierarchy.md"
_HEADER_END_MARKER = "<!-- Entries appended below this line by Process Organiser. Do not edit by hand. -->"

_DOMAIN_RE = re.compile(r"^Domain:\s*(.+?)\s*$")
_SUBSECTION_RE = re.compile(r"^Sub-section:\s*(.+?)\s*$")
_ENTRY_RE = re.compile(r"^\[(FEAT-\d+)\]\s*(.+?)\s+—\s+added\s+(\S+)\s*$")


def _phd_path() -> Path:
    return repo_root() / _PHD_PATH


# Parsed structure:
#   { domain_name -> OrderedDict[ sub_section_name -> list[entry_str] ] }
ParsedPHD = OrderedDict[str, OrderedDict[str, list[str]]]


def _split_header(text: str) -> tuple[str, str]:
    """Return (header_block, entries_block). Header includes the marker line."""
    if _HEADER_END_MARKER in text:
        idx = text.index(_HEADER_END_MARKER) + len(_HEADER_END_MARKER)
        return text[:idx], text[idx:]
    # No marker — entire file is treated as header, entries block is empty.
    return text.rstrip() + "\n", ""


def parse_entries(entries_block: str) -> ParsedPHD:
    parsed: ParsedPHD = OrderedDict()
    current_domain: str | None = None
    current_sub: str | None = None

    for raw in entries_block.splitlines():
        line = raw.strip()
        if not line:
            continue
        if (m := _DOMAIN_RE.match(line)) is not None:
            current_domain = m.group(1)
            parsed.setdefault(current_domain, OrderedDict())
            current_sub = None
            continue
        if (m := _SUBSECTION_RE.match(line)) is not None:
            if current_domain is None:
                continue  # malformed, skip
            current_sub = m.group(1)
            parsed[current_domain].setdefault(current_sub, [])
            continue
        if (m := _ENTRY_RE.match(line)) is not None:
            if current_domain is None or current_sub is None:
                continue
            parsed[current_domain][current_sub].append(line)
            continue
        # Unknown line — skip rather than corrupt.
    return parsed


def render_entries(parsed: ParsedPHD) -> str:
    """Render parsed structure back to markdown text."""
    if not parsed:
        return "\n"
    out: list[str] = ["\n"]
    for domain, subs in parsed.items():
        out.append(f"Domain: {domain}\n")
        for sub_name, entries in subs.items():
            out.append(f"Sub-section: {sub_name}\n")
            # Sort by FEAT-NNN within each sub-section. Entries are stable
            # tuples; sort key extracts the numeric portion of FEAT-NNN.
            sorted_entries = sorted(entries, key=_entry_sort_key)
            for entry in sorted_entries:
                out.append(entry + "\n")
            out.append("\n")
        out.append("\n")
    return "".join(out)


def _entry_sort_key(entry_line: str) -> tuple[int, str]:
    m = _ENTRY_RE.match(entry_line)
    if not m:
        return (10**9, entry_line)
    feat_id = m.group(1)
    try:
        n = int(feat_id.split("-", 1)[1])
    except ValueError:
        n = 10**9
    return (n, entry_line)


def update_phd(entry: PHEntry) -> Path:
    """Read the PHD, append `entry` under (domain, sub_section), write back atomically.

    Returns the absolute path of the file. Idempotent on the (feature_id,
    domain, sub_section) tuple — adding the same entry twice is a no-op.
    """
    path = _phd_path()
    if not path.exists():
        # First run only — write the canonical header so the marker exists.
        path.write_text(
            "# Process Hierarchy\n\n"
            "This document is the single source of truth for every shipped feature in\n"
            "Arshad.AI. The Process Organiser agent appends to this file after each\n"
            "pipeline run; entries are never removed or rewritten in place.\n\n"
            "Format:\n```\n"
            "Domain: <Domain Name>\n"
            "Sub-section: <Sub-section Name>\n"
            "[FEAT-NNN] <Feature name> — added <ISO timestamp>\n```\n\n"
            f"{_HEADER_END_MARKER}\n"
        )

    text = path.read_text()
    header, entries_block = _split_header(text)
    parsed = parse_entries(entries_block)

    # Append the new entry — idempotent.
    parsed.setdefault(entry.domain, OrderedDict()).setdefault(entry.sub_section, [])
    new_line = f"[{entry.feature_id}] {entry.feature_name} — added {entry.added_at}"
    if new_line not in parsed[entry.domain][entry.sub_section]:
        parsed[entry.domain][entry.sub_section].append(new_line)

    new_text = header + render_entries(parsed)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(new_text)
    os.replace(tmp, path)
    return path
