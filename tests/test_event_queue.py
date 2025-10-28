from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.events.event_queue import EventQueue


def test_events_for_specific_day_are_deterministic():
    queue = EventQueue()
    queue.schedule(5, "alpha")
    queue.schedule(5, "beta", {"payload": True})
    queue.schedule(3, "earlier")
    queue.schedule(5, "gamma")

    events_for_day = queue.events_for_day(5)
    assert [event.event_type for event in events_for_day] == [
        "alpha",
        "beta",
        "gamma",
    ]

    popped = queue.pop_events_for_day(5)
    assert [event.event_type for event in popped] == ["alpha", "beta", "gamma"]
    assert queue.events_for_day(5) == []

    # The earlier event should still be pending until its day is processed.
    assert queue.has_events()
    remaining = queue.pop_events_for_day(3)
    assert [event.event_type for event in remaining] == ["earlier"]
    assert not queue.has_events()


def test_schedule_in_respects_relative_days():
    queue = EventQueue()
    queue.schedule_in(2, current_day=4, event_type="future", payload={"value": 1})

    events = queue.pop_events_for_day(6)
    assert len(events) == 1
    event = events[0]
    assert event.day == 6
    assert event.event_type == "future"
    assert event.payload == {"value": 1}


def test_large_batch_preserves_order():
    queue = EventQueue()
    for index in range(500):
        queue.schedule(10, f"evt-{index}")

    popped = queue.pop_events_for_day(10)
    assert [event.event_type for event in popped] == [f"evt-{index}" for index in range(500)]
    assert not queue.has_events()


@pytest.mark.parametrize(
    "schedule_days, expected",
    [
        ((1, 5, 3, 5), [1, 3, 5]),
        ((2,), [2]),
        ((), []),
    ],
)
def test_upcoming_days_sorted(schedule_days, expected):
    queue = EventQueue()
    for day in schedule_days:
        queue.schedule(day, f"event-{day}")

    assert queue.upcoming_days() == expected
