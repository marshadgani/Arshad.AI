#!/usr/bin/env python3
"""Strip heredoc bodies + quoted-string content from a bash command line.

Reads the command on stdin, writes the sanitized version on stdout.

Used by bash-guard.sh so dangerous-pattern regexes don't trigger on
strings inside commit messages, heredocs, or other quoted argument bodies.
"""

import re
import sys

_HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1(.*?)^\2\s*$",
    re.DOTALL | re.MULTILINE,
)


def strip_heredocs(s: str) -> str:
    return _HEREDOC.sub(" ", s)


def blank_quoted(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch in ("'", '"'):
            q = ch
            out.append(q)
            i += 1
            while i < n and s[i] != q:
                if q == '"' and s[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
            if i < n:
                out.append(q)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


if __name__ == "__main__":
    src = sys.stdin.read()
    sys.stdout.write(blank_quoted(strip_heredocs(src)))
