"""LIKE-pattern construction for user-supplied search terms.

`LIKE` treats `%` as "any run of characters" and `_` as "any single character".
Those are wildcards *in the pattern*, and a search term is data, not pattern —
so a user searching for `100%` or `a_b` silently matched far more than they
asked for, with no way to see that it had happened. The value is always bound
as a parameter, so this was never an injection hole; it is a correctness hole.

`escape_like` neutralises the three characters that can change a pattern's
meaning, and every call site must then pass `escape=LIKE_ESCAPE_CHAR` to
`.like()` / `.ilike()` so the engine actually honours the backslash. Escaping
without the clause is the common half-fix and matches nothing; the clause
without escaping turns every literal backslash in a search into an error.

Verified on both engines this project runs: SQLite renders
`... LIKE ? ESCAPE '\'` and Postgres parses `'\'` as one backslash
(`standard_conforming_strings` is on by default since 9.1).
"""

LIKE_ESCAPE_CHAR = "\\"

_LIKE_WILDCARDS = ("%", "_")


def escape_like(term: str, escape: str = LIKE_ESCAPE_CHAR) -> str:
    """Escape LIKE metacharacters in a user-supplied term.

    The escape character itself is escaped first, so a term that already
    contains a backslash cannot break out of the pattern it is being placed in.
    """
    out = term.replace(escape, escape * 2)
    for wildcard in _LIKE_WILDCARDS:
        out = out.replace(wildcard, escape + wildcard)
    return out


def like_contains(term: str) -> str:
    """Pattern matching rows that contain `term` literally."""
    return f"%{escape_like(term)}%"


def like_startswith(term: str) -> str:
    """Pattern matching rows that start with `term` literally."""
    return f"{escape_like(term)}%"