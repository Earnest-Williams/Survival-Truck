"""Tests covering crew trait persistence and lifecycle transitions."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.crew import Crew, CrewMember, Need, NeedName, TraitImpact


def test_crew_member_serialization_persists_traits() -> None:
    member = CrewMember(
        name="Alex",
        morale=65.0,
        needs={NeedName.HUNGER: Need(name=NeedName.HUNGER, value=80.0)},
        traits={"optimist", "tough"},
        perks={"medic"},
    )

    payload = member.to_dict()

    assert set(payload["traits"]) == {"optimist", "tough"}
    assert payload["perks"] == ["medic"]

    restored = CrewMember.from_dict(payload)

    assert restored.traits == {"optimist", "tough"}
    assert restored.perks == {"medic"}


def test_recruitment_and_loss_apply_trait_impacts() -> None:
    crew = Crew(
        members=[CrewMember(name="Taylor", morale=50.0)],
        trait_impacts={"optimist": TraitImpact(recruit_morale=2.5, loss_morale=-4.0)},
        perk_impacts={"medic": TraitImpact(recruit_morale=1.0, loss_morale=-1.5)},
    )

    recruit = CrewMember(name="Jordan", morale=60.0, traits={"optimist"}, perks={"medic"})

    recruitment_event = crew.recruit_member(recruit, base_morale_boost=1.0, reason="test_recruit")

    assert recruitment_event.event == "recruitment"
    assert recruitment_event.member == "Jordan"
    assert recruitment_event.traits == ["optimist"]
    assert recruitment_event.perks == ["medic"]
    assert "Taylor" in recruitment_event.morale_changes
    assert pytest.approx(recruitment_event.morale_changes["Taylor"], rel=1e-6) == 4.5
    assert pytest.approx(crew.get_member_morale("Taylor"), rel=1e-6) == 54.5
    # Newly recruited member should not be affected by their own aura adjustments.
    assert "Jordan" not in recruitment_event.morale_changes

    loss_event = crew.lose_member("Jordan", base_morale_penalty=-1.0, reason="test_loss")

    assert loss_event is not None
    assert loss_event.event == "loss"
    assert loss_event.member == "Jordan"
    assert loss_event.traits == ["optimist"]
    assert loss_event.perks == ["medic"]
    assert not crew.has_member("Jordan")
    assert "Taylor" in loss_event.morale_changes
    assert pytest.approx(loss_event.morale_changes["Taylor"], rel=1e-6) == -6.5
    assert pytest.approx(crew.get_member_morale("Taylor"), rel=1e-6) == 48.0
