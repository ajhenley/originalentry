"""Time on task (T8.7, I4.3).

The figure the pilot most needs, and the one that is easiest to get wrong: a student who leaves a
tab open overnight has not been working all night. Gaps longer than the break threshold count for
nothing; everything else is summed.
"""

from datetime import UTC, datetime, timedelta

from originalentry.grading.time_on_task import BREAK_AFTER, minutes_from

START = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


def _times(*minutes):
    return [START + timedelta(minutes=m) for m in minutes]


def test_no_activity_is_no_time():
    assert minutes_from([]) == 0
    assert minutes_from(_times(0)) == 0


def test_steady_work_is_summed():
    assert minutes_from(_times(0, 5, 12, 20)) == 20


def test_a_long_gap_is_a_break_and_counts_for_nothing():
    overnight = BREAK_AFTER.total_seconds() / 60 + 600
    assert minutes_from(_times(0, 10, 10 + overnight, 10 + overnight + 15)) == 25


def test_times_out_of_order_are_read_in_order():
    assert minutes_from(_times(20, 0, 5)) == 20
