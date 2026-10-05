"""Progress normalisation for worker-reported values.

One definition of the rule, because there were two and they had already drifted:
`services/provider_client._ImageReducer` keyed on the `value_unit` field the
current worker contract carries, and `api/routes/worker_ws._coerce_percent` still
used the older `0 <= value <= 1 means a fraction` heuristic — so a canonical
worker event carrying `value == 1` (one percent done) was recorded as 100% by the
socket half and as 1% by the client half. It is silent, and it lands on the single
most-watched number in the UI.

`value_unit` is authoritative when present: `provider_core/models.py` declares
every worker on the current contract as sending `"percent"`. A container deployed
before that field existed omits it rather than sending it wrong, so the heuristic
is retained for exactly that case and nothing else.

The result is clamped to 0..100 because migration 047 added
`CHECK (progress BETWEEN 0 AND 100)` on `jobs`; an out-of-range write raised
IntegrityError inside the session context, propagated to the socket-level
handler and dropped the worker, leaving the job non-terminal.
"""

from __future__ import annotations

from typing import Any


def coerce_worker_percent(value: Any, value_unit: str | None = None) -> int:
    """Normalise a worker-reported progress value to a 0..100 integer.

    Args:
        value: the reported number. Non-numeric input becomes 0.
        value_unit: `"percent"` for every worker on the current contract. When it
            is absent the value is treated as a fraction if it is in 0..1,
            which is what pre-`value_unit` containers sent.

    Returns:
        An integer in 0..100.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number != number:  # NaN
        return 0
    if value_unit == "percent":
        percent = number
    else:
        percent = number * 100 if 0 <= number <= 1 else number
    return max(0, min(100, int(percent)))