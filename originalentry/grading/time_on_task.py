"""How long the work took (T8.7, I4.3).

The rule is deliberately dull: sort a workspace's activity, sum the gaps between one action and
the next, and treat anything longer than the break threshold as a break worth nothing. A student
who leaves a tab open overnight has not been working all night, and a figure that says otherwise
would be worse than no figure at all.

Pure: it takes timestamps and returns minutes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

BREAK_AFTER = timedelta(minutes=20)


def minutes_from(times: list[datetime]) -> float:
    ordered = sorted(times)
    total = timedelta()
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        gap = later - earlier
        if gap <= BREAK_AFTER:
            total += gap
    return total.total_seconds() / 60


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def quartiles(values: list[float]) -> tuple[float, float, float]:
    """Lower quartile, median and upper quartile — the shape of the distribution (I4.3)."""
    if not values:
        return 0.0, 0.0, 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    lower = ordered[:middle]
    upper = ordered[middle + 1:] if len(ordered) % 2 else ordered[middle:]
    return median(lower), median(ordered), median(upper)
