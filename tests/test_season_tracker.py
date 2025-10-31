from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.time.season_tracker import SeasonTracker


@pytest.mark.parametrize("days_per_season", [5, 10])
def test_days_until_next_season_resets_on_season_start(days_per_season: int) -> None:
    tracker = SeasonTracker(days_per_season=days_per_season)

    assert tracker.days_until_next_season() == days_per_season

    for _ in range(days_per_season):
        tracker.advance_day()

    assert tracker.days_until_next_season() == days_per_season


def test_days_until_next_season_counts_down_mid_season() -> None:
    tracker = SeasonTracker(days_per_season=7)

    tracker.advance_day()
    assert tracker.days_until_next_season() == 6

    tracker.advance_day()
    tracker.advance_day()
    assert tracker.days_until_next_season() == 4
