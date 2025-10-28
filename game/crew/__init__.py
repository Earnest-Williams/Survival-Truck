"""Crew simulation models including needs, morale, and skill checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import random
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence


class NeedName(str, Enum):
    """Wellbeing categories tracked for each crew member."""

    HUNGER = "hunger"
    FATIGUE = "fatigue"
    HEALTH = "health"
    COMFORT = "comfort"


@dataclass
class Need:
    """A single need meter that decays over time."""

    name: NeedName
    value: float = 100.0
    decay_per_day: float = 5.0
    min_value: float = 0.0
    max_value: float = 100.0

    def apply_decay(self, modifier: float = 1.0) -> float:
        """Reduce the value by its decay amount and return the delta."""

        if modifier < 0:
            raise ValueError("modifier must be non-negative")
        previous = self.value
        decay = self.decay_per_day * modifier
        if decay <= 0:
            return 0.0
        self.value = max(self.min_value, self.value - decay)
        return self.value - previous

    def adjust(self, amount: float) -> float:
        """Apply a manual adjustment and return the resulting value."""

        self.value = max(self.min_value, min(self.max_value, self.value + amount))
        return self.value

    @property
    def satisfaction(self) -> float:
        """Return the normalized satisfaction level between 0 and 1."""

        if self.max_value <= self.min_value:
            return 1.0
        return (self.value - self.min_value) / (self.max_value - self.min_value)


class SkillType(str, Enum):
    """Primary skills used when resolving gameplay checks."""

    SCAVENGING = "scavenging"
    NEGOTIATION = "negotiation"
    ENGINEERING = "engineering"
    MEDICINE = "medicine"


@dataclass
class CrewMember:
    """A single survivor travelling with the truck."""

    name: str
    morale: float = 50.0
    needs: MutableMapping[NeedName, Need] = field(default_factory=dict)
    skills: MutableMapping[SkillType, int] = field(default_factory=dict)
    relationships: MutableMapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for need_name in NeedName:
            self.needs.setdefault(need_name, Need(name=need_name))
        self._clamp_morale()
        self._normalize_relationships()

    def _clamp_morale(self) -> None:
        self.morale = max(0.0, min(100.0, float(self.morale)))

    def _normalize_relationships(self) -> None:
        for key, value in list(self.relationships.items()):
            self.relationships[key] = max(-100.0, min(100.0, float(value)))

    def adjust_relationship(self, other: str, delta: float) -> float:
        """Modify the opinion score towards another crew member."""

        value = self.relationships.get(other, 0.0) + delta
        clamped = max(-100.0, min(100.0, value))
        self.relationships[other] = clamped
        return clamped

    def relationship_modifier(self, crew: Mapping[str, "CrewMember"]) -> float:
        """Compute a morale modifier derived from social ties."""

        if not self.relationships:
            return 0.0
        total = 0.0
        count = 0
        for other, score in self.relationships.items():
            if other not in crew:
                continue
            total += score
            count += 1
        if count == 0:
            return 0.0
        average = total / count
        return average / 200.0  # Convert the -100..100 scale to roughly -0.5..0.5

    def skill_value(self, skill: SkillType) -> int:
        """Return the trained value for ``skill``."""

        return int(self.skills.get(skill, 0))

    def morale_modifier(self) -> float:
        """Return a modifier applied to skill checks based on morale."""

        return (self.morale - 50.0) / 10.0

    def advance_day(self, crew: Mapping[str, "CrewMember"], *, decay_modifier: float = 1.0) -> None:
        """Apply daily need decay and update morale accordingly."""

        stress = 0.0
        for need in self.needs.values():
            need.apply_decay(decay_modifier)
            if need.satisfaction < 0.5:
                stress += (0.5 - need.satisfaction)
        relationship_boost = self.relationship_modifier(crew)
        morale_change = relationship_boost * 10.0 - stress * 6.0
        self.morale += morale_change
        self._clamp_morale()

    def apply_rest(self, quality: float) -> None:
        """Improve fatigue and comfort after resting."""

        fatigue = self.needs[NeedName.FATIGUE]
        comfort = self.needs[NeedName.COMFORT]
        fatigue.adjust(quality)
        comfort.adjust(quality * 0.5)
        self.morale += quality * 0.1
        self._clamp_morale()

    def to_dict(self) -> Dict[str, object]:
        """Serialize the crew member to a JSON compatible mapping."""

        return {
            "name": self.name,
            "morale": self.morale,
            "needs": {need.name.value: need.value for need in self.needs.values()},
            "decay": {need.name.value: need.decay_per_day for need in self.needs.values()},
            "skills": {skill.value: int(value) for skill, value in self.skills.items()},
            "relationships": dict(self.relationships),
        }

    @staticmethod
    def from_dict(payload: Mapping[str, object]) -> "CrewMember":
        """Deserialize a :class:`CrewMember` from a mapping."""

        name = str(payload.get("name", ""))
        morale = float(payload.get("morale", 50.0))
        needs_payload = payload.get("needs", {})
        decay_payload = payload.get("decay", {})
        needs: Dict[NeedName, Need] = {}
        if isinstance(needs_payload, Mapping):
            for key, value in needs_payload.items():
                try:
                    need_name = NeedName(str(key))
                except ValueError:
                    continue
                decay = 5.0
                if isinstance(decay_payload, Mapping):
                    decay = float(decay_payload.get(key, decay))
                needs[need_name] = Need(name=need_name, value=float(value), decay_per_day=decay)
        skills_payload = payload.get("skills", {})
        skills: Dict[SkillType, int] = {}
        if isinstance(skills_payload, Mapping):
            for key, value in skills_payload.items():
                try:
                    skill = SkillType(str(key))
                except ValueError:
                    continue
                skills[skill] = int(value)
        relationships_payload = payload.get("relationships", {})
        relationships: Dict[str, float] = {}
        if isinstance(relationships_payload, Mapping):
            for key, value in relationships_payload.items():
                relationships[str(key)] = float(value)
        return CrewMember(
            name=name,
            morale=morale,
            needs=needs,
            skills=skills,
            relationships=relationships,
        )


@dataclass(frozen=True)
class SkillCheckResult:
    """Outcome information from a skill check."""

    skill: SkillType
    difficulty: float
    roll: float
    success: bool
    margin: float
    participants: Sequence[str]


def perform_skill_check(
    actor: CrewMember,
    skill: SkillType,
    difficulty: float,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    """Resolve an individual skill check for ``actor``."""

    rng = rng or random.Random()
    base = actor.skill_value(skill) + actor.morale_modifier()
    roll = base + rng.randint(1, 20)
    margin = roll - difficulty
    return SkillCheckResult(
        skill=skill,
        difficulty=difficulty,
        roll=roll,
        success=margin >= 0,
        margin=margin,
        participants=[actor.name],
    )


def team_skill_check(
    actors: Iterable[CrewMember],
    skill: SkillType,
    difficulty: float,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    """Resolve a cooperative skill check for multiple crew members."""

    participants: List[str] = []
    contributions: List[float] = []
    for actor in actors:
        participants.append(actor.name)
        contributions.append(actor.skill_value(skill) + actor.morale_modifier())
    if not contributions:
        raise ValueError("team_skill_check requires at least one participant")
    rng = rng or random.Random()
    contributions.sort(reverse=True)
    base = sum(contributions[:2]) + sum(contribution * 0.25 for contribution in contributions[2:])
    roll = base + rng.randint(1, 20)
    margin = roll - difficulty
    return SkillCheckResult(
        skill=skill,
        difficulty=difficulty,
        roll=roll,
        success=margin >= 0,
        margin=margin,
        participants=participants,
    )


class Crew:
    """Container managing a travelling party of crew members."""

    def __init__(
        self,
        members: Iterable[CrewMember] | None = None,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self._members: Dict[str, CrewMember] = {member.name: member for member in (members or [])}
        self.rng = rng or random.Random()

    @property
    def members(self) -> Mapping[str, CrewMember]:
        return self._members

    def add_member(self, member: CrewMember) -> None:
        self._members[member.name] = member
        for other in self._members.values():
            if other is member:
                continue
            other.relationships.setdefault(member.name, 0.0)
            member.relationships.setdefault(other.name, 0.0)
            other._normalize_relationships()
        member._normalize_relationships()

    def remove_member(self, name: str) -> Optional[CrewMember]:
        member = self._members.pop(name, None)
        if member is None:
            return None
        for other in self._members.values():
            other.relationships.pop(name, None)
        return member

    def advance_day(self, *, decay_modifier: float = 1.0) -> None:
        """Advance all crew members by one day, applying morale drift."""

        for member in list(self._members.values()):
            member.advance_day(self._members, decay_modifier=decay_modifier)
        self._resolve_social_drift()

    def _resolve_social_drift(self) -> None:
        for member in self._members.values():
            for other_name, score in list(member.relationships.items()):
                if other_name not in self._members:
                    continue
                other_score = self._members[other_name].relationships.get(member.name, 0.0)
                equilibrium = (score + other_score) / 2
                member.relationships[other_name] = equilibrium
        self._apply_random_interactions()

    def _apply_random_interactions(self) -> None:
        names = list(self._members)
        if len(names) < 2:
            return
        self.rng.shuffle(names)
        for first, second in zip(names[::2], names[1::2]):
            a = self._members[first]
            b = self._members[second]
            attitude = (a.relationships.get(second, 0.0) + b.relationships.get(first, 0.0)) / 2
            delta = self.rng.uniform(-2.0, 3.0)
            if attitude > 25:
                delta = abs(delta)
            elif attitude < -25:
                delta = -abs(delta)
            a.adjust_relationship(second, delta)
            b.adjust_relationship(first, delta)

    def skill_check(
        self,
        members: Sequence[str],
        skill: SkillType,
        difficulty: float,
    ) -> SkillCheckResult:
        """Run a cooperative skill check for a subset of the crew."""

        actors = [self._members[name] for name in members if name in self._members]
        if not actors:
            raise ValueError("No matching crew members provided for skill check")
        if len(actors) == 1:
            return perform_skill_check(actors[0], skill, difficulty, rng=self.rng)
        return team_skill_check(actors, skill, difficulty, rng=self.rng)


__all__ = [
    "Crew",
    "CrewMember",
    "Need",
    "NeedName",
    "SkillCheckResult",
    "SkillType",
    "perform_skill_check",
    "team_skill_check",
]
