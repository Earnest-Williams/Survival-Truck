"""Crew simulation models including needs, morale, and skill checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    MutableSet,
    Sequence,
    Set,
    TypedDict,
)

import polars as pl
from numpy.random import Generator, default_rng

from ..world.rng import WorldRandomness


class NeedName(str, Enum):
    """Wellbeing categories tracked for each crew member."""

    HUNGER = "hunger"
    FATIGUE = "fatigue"
    HEALTH = "health"
    COMFORT = "comfort"


_MEMBER_FRAME_SCHEMA: Dict[str, pl.datatypes.DataType] = {
    "name": pl.String,
    "morale": pl.Float64,
}
for _need in NeedName:
    prefix = _need.value
    _MEMBER_FRAME_SCHEMA[f"{prefix}_value"] = pl.Float64
    _MEMBER_FRAME_SCHEMA[f"{prefix}_decay"] = pl.Float64
    _MEMBER_FRAME_SCHEMA[f"{prefix}_min"] = pl.Float64
    _MEMBER_FRAME_SCHEMA[f"{prefix}_max"] = pl.Float64

_RELATIONSHIP_FRAME_SCHEMA: Dict[str, pl.datatypes.DataType] = {
    "source": pl.String,
    "target": pl.String,
    "score": pl.Float64,
}


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


class CrewMemberPayload(TypedDict, total=False):
    """Serialized representation of a :class:`CrewMember`."""

    name: str
    morale: float | int
    needs: Mapping[str, float | int]
    decay: Mapping[str, float | int]
    skills: Mapping[str, int | float]
    relationships: Mapping[str, float | int]
    traits: Iterable[str]
    perks: Iterable[str]


@dataclass
class CrewMember:
    """A single survivor travelling with the truck."""

    name: str
    morale: float = 50.0
    needs: MutableMapping[NeedName, Need] = field(default_factory=dict)
    skills: MutableMapping[SkillType, int] = field(default_factory=dict)
    relationships: MutableMapping[str, float] = field(default_factory=dict)
    traits: MutableSet[str] = field(default_factory=set)
    perks: MutableSet[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        for need_name in NeedName:
            self.needs.setdefault(need_name, Need(name=need_name))
        self._clamp_morale()
        self._normalize_relationships()
        self.traits = {str(trait) for trait in self.traits}
        self.perks = {str(perk) for perk in self.perks}

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

    def to_dict(self) -> CrewMemberPayload:
        """Serialize the crew member to a JSON compatible mapping."""

        return {
            "name": self.name,
            "morale": self.morale,
            "needs": {need.name.value: need.value for need in self.needs.values()},
            "decay": {need.name.value: need.decay_per_day for need in self.needs.values()},
            "skills": {skill.value: int(value) for skill, value in self.skills.items()},
            "relationships": dict(self.relationships),
            "traits": sorted(self.traits),
            "perks": sorted(self.perks),
        }

    @staticmethod
    def from_dict(payload: CrewMemberPayload | Mapping[str, object]) -> "CrewMember":
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
        traits_payload = payload.get("traits", set())
        traits: Set[str] = set()
        if isinstance(traits_payload, Iterable) and not isinstance(traits_payload, (str, bytes)):
            traits = {str(item) for item in traits_payload}
        perks_payload = payload.get("perks", set())
        perks: Set[str] = set()
        if isinstance(perks_payload, Iterable) and not isinstance(perks_payload, (str, bytes)):
            perks = {str(item) for item in perks_payload}
        return CrewMember(
            name=name,
            morale=morale,
            needs=needs,
            skills=skills,
            relationships=relationships,
            traits=traits,
            perks=perks,
        )


@dataclass(frozen=True)
class TraitImpact:
    """Defines how a trait or perk influences crew morale events."""

    recruit_morale: float = 0.0
    loss_morale: float = 0.0


@dataclass(frozen=True)
class CrewLifecycleEvent:
    """Details of a crew lifecycle transition such as recruitment or loss."""

    event: str
    member: str
    morale_changes: Mapping[str, float]
    traits: Sequence[str]
    perks: Sequence[str]
    reason: str | None = None


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
    rng: Generator | None = None,
) -> SkillCheckResult:
    """Resolve an individual skill check for ``actor``."""

    rng = rng or default_rng()
    base = actor.skill_value(skill) + actor.morale_modifier()
    roll = base + int(rng.integers(1, 20, endpoint=True))
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
    rng: Generator | None = None,
) -> SkillCheckResult:
    """Resolve a cooperative skill check for multiple crew members."""

    participants: List[str] = []
    contributions: List[float] = []
    for actor in actors:
        participants.append(actor.name)
        contributions.append(actor.skill_value(skill) + actor.morale_modifier())
    if not contributions:
        raise ValueError("team_skill_check requires at least one participant")
    rng = rng or default_rng()
    contributions.sort(reverse=True)
    base = sum(contributions[:2]) + sum(contribution * 0.25 for contribution in contributions[2:])
    roll = base + int(rng.integers(1, 20, endpoint=True))
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
        rng: Generator | None = None,
        randomness: WorldRandomness | None = None,
        trait_impacts: Mapping[str, TraitImpact] | None = None,
        perk_impacts: Mapping[str, TraitImpact] | None = None,
    ) -> None:
        self._members: Dict[str, CrewMember] = {}
        if randomness is not None:
            self.rng = randomness.generator("crew")
        else:
            self.rng = rng or default_rng()
        self.trait_impacts: Dict[str, TraitImpact] = dict(trait_impacts or {})
        self.perk_impacts: Dict[str, TraitImpact] = dict(perk_impacts or {})
        for member in members or []:
            self._register_member(member)

    @property
    def members(self) -> Mapping[str, CrewMember]:
        return self._members

    def add_member(self, member: CrewMember) -> None:
        self._register_member(member)

    def recruit_member(
        self,
        member: CrewMember,
        *,
        base_morale_boost: float = 1.0,
        reason: str | None = None,
    ) -> CrewLifecycleEvent:
        """Add ``member`` and adjust morale based on traits and perks."""

        if member.name in self._members:
            raise ValueError(f"Crew already contains member named {member.name!r}")
        self._register_member(member)
        morale_changes: Dict[str, float] = {}
        if base_morale_boost:
            morale_changes.update(self._adjust_morale(base_morale_boost, exclude={member.name}))
        bonus = self._personality_morale_delta(member, event="recruit")
        if bonus:
            self._merge_morale_changes(
                morale_changes,
                self._adjust_morale(bonus, exclude={member.name}),
            )
        return CrewLifecycleEvent(
            event="recruitment",
            member=member.name,
            morale_changes=dict(morale_changes),
            traits=sorted(member.traits),
            perks=sorted(member.perks),
            reason=reason,
        )

    def remove_member(self, name: str) -> CrewMember | None:
        return self._deregister_member(name)

    def lose_member(
        self,
        name: str,
        *,
        base_morale_penalty: float = -2.0,
        reason: str | None = None,
    ) -> CrewLifecycleEvent | None:
        """Remove the crew member named ``name`` and apply morale changes."""

        member = self._deregister_member(name)
        if member is None:
            return None
        morale_changes: Dict[str, float] = {}
        if base_morale_penalty:
            morale_changes.update(self._adjust_morale(base_morale_penalty))
        penalty = self._personality_morale_delta(member, event="loss")
        if penalty:
            self._merge_morale_changes(morale_changes, self._adjust_morale(penalty))
        return CrewLifecycleEvent(
            event="loss",
            member=member.name,
            morale_changes=dict(morale_changes),
            traits=sorted(member.traits),
            perks=sorted(member.perks),
            reason=reason,
        )

    def advance_day(self, *, decay_modifier: float = 1.0) -> None:
        """Advance all crew members by one day, applying morale drift."""

        if not self._members:
            return
        member_frame = self._member_frame()
        relationship_frame = self._relationship_frame()
        updated = self._advance_member_frame(
            member_frame,
            relationship_frame,
            decay_modifier,
        )
        self._apply_member_frame(updated)
        self._resolve_social_drift()

    def _resolve_social_drift(self) -> None:
        if not self._members:
            return
        relationship_frame = self._relationship_frame()
        if relationship_frame.is_empty():
            self._apply_random_interactions()
            return
        equilibrated = self._equilibrate_relationships(relationship_frame)
        self._apply_relationship_frame(equilibrated)
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
            delta = float(self.rng.uniform(-2.0, 3.0))
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

    # ------------------------------------------------------------------
    def _register_member(self, member: CrewMember) -> None:
        self._members[member.name] = member
        for other in self._members.values():
            if other is member:
                continue
            other.relationships.setdefault(member.name, 0.0)
            member.relationships.setdefault(other.name, 0.0)
            other._normalize_relationships()
        member._normalize_relationships()

    def _deregister_member(self, name: str) -> CrewMember | None:
        member = self._members.pop(name, None)
        if member is None:
            return None
        for other in self._members.values():
            other.relationships.pop(name, None)
        return member

    def _adjust_morale(
        self,
        delta: float,
        *,
        exclude: Set[str] | None = None,
    ) -> Dict[str, float]:
        if not self._members or delta == 0:
            return {}
        frame = self._member_frame()
        if exclude:
            frame = frame.filter(~pl.col("name").is_in(list(exclude)))
        if frame.is_empty():
            return {}
        adjusted = frame.with_columns(
            (pl.col("morale") + delta)
            .clip(lower_bound=0.0, upper_bound=100.0)
            .alias("_morale_next")
        )
        result: Dict[str, float] = {}
        for row in adjusted.select(
            "name",
            "morale",
            "_morale_next",
        ).to_dicts():
            name = str(row["name"])
            member = self._members.get(name)
            if member is None:
                continue
            before = member.morale
            member.morale = float(row["_morale_next"])
            member._clamp_morale()
            result[name] = member.morale - before
        return result

    @staticmethod
    def _merge_morale_changes(
        base: Dict[str, float],
        extra: Mapping[str, float],
    ) -> None:
        for name, delta in extra.items():
            base[name] = base.get(name, 0.0) + delta

    def _personality_morale_delta(self, member: CrewMember, *, event: str) -> float:
        traits_delta = self._aggregate_impacts(member.traits, self.trait_impacts, event)
        perks_delta = self._aggregate_impacts(member.perks, self.perk_impacts, event)
        return traits_delta + perks_delta

    # ------------------------------------------------------------------
    def _member_frame(self) -> pl.DataFrame:
        if not self._members:
            return pl.DataFrame(schema=_MEMBER_FRAME_SCHEMA)
        rows: List[Dict[str, float | str]] = []
        for member in self._members.values():
            row: Dict[str, float | str] = {
                "name": member.name,
                "morale": float(member.morale),
            }
            for need_name in NeedName:
                need = member.needs.get(need_name, Need(name=need_name))
                prefix = need_name.value
                row[f"{prefix}_value"] = float(need.value)
                row[f"{prefix}_decay"] = float(need.decay_per_day)
                row[f"{prefix}_min"] = float(need.min_value)
                row[f"{prefix}_max"] = float(need.max_value)
            rows.append(row)
        return pl.DataFrame(rows, schema=_MEMBER_FRAME_SCHEMA)

    def _relationship_frame(self) -> pl.DataFrame:
        if not self._members:
            return pl.DataFrame(schema=_RELATIONSHIP_FRAME_SCHEMA)
        rows: List[Dict[str, float | str]] = []
        for name, member in self._members.items():
            for other, score in member.relationships.items():
                rows.append(
                    {
                        "source": name,
                        "target": str(other),
                        "score": float(score),
                    }
                )
        if not rows:
            return pl.DataFrame(schema=_RELATIONSHIP_FRAME_SCHEMA)
        return pl.DataFrame(rows, schema=_RELATIONSHIP_FRAME_SCHEMA)

    def _apply_member_frame(self, frame: pl.DataFrame) -> None:
        for row in frame.to_dicts():
            name = str(row.get("name", ""))
            member = self._members.get(name)
            if member is None:
                continue
            member.morale = float(row.get("morale", member.morale))
            member._clamp_morale()
            for need_name in NeedName:
                prefix = need_name.value
                value_key = f"{prefix}_value"
                if value_key in row:
                    member.needs[need_name].value = float(row[value_key])

    def _apply_relationship_frame(self, frame: pl.DataFrame) -> None:
        updates: Dict[str, Dict[str, float]] = {name: {} for name in self._members}
        for row in frame.to_dicts():
            source = str(row.get("source", ""))
            target = str(row.get("target", ""))
            score = float(row.get("score", 0.0))
            updates.setdefault(source, {})[target] = score
        for name, member in self._members.items():
            new_scores = updates.get(name, {})
            to_remove = [key for key in member.relationships if key not in new_scores]
            for key in to_remove:
                member.relationships.pop(key, None)
            for other, score in new_scores.items():
                member.relationships[other] = score

    def _advance_member_frame(
        self,
        frame: pl.DataFrame,
        relationships: pl.DataFrame,
        decay_modifier: float,
    ) -> pl.DataFrame:
        if frame.is_empty():
            return frame
        lazy = frame.lazy()
        stress_columns: List[pl.Expr] = []
        for need_name in NeedName:
            prefix = need_name.value
            value_col = f"{prefix}_value"
            min_col = f"{prefix}_min"
            max_col = f"{prefix}_max"
            decay_col = f"{prefix}_decay"
            new_value_expr = pl.max_horizontal(
                pl.col(min_col),
                pl.col(value_col) - pl.col(decay_col) * decay_modifier,
            )
            satisfaction_expr = (
                pl.when(pl.col(max_col) <= pl.col(min_col))
                .then(1.0)
                .otherwise(
                    (new_value_expr - pl.col(min_col))
                    / (pl.col(max_col) - pl.col(min_col))
                )
            )
            stress_expr = (
                pl.when(satisfaction_expr < 0.5)
                .then(0.5 - satisfaction_expr)
                .otherwise(0.0)
            )
            lazy = lazy.with_columns(
                new_value_expr.alias(value_col),
                satisfaction_expr.alias(f"{prefix}_satisfaction"),
                stress_expr.alias(f"{prefix}_stress"),
            )
            stress_columns.append(pl.col(f"{prefix}_stress"))
        if stress_columns:
            total_stress = pl.fold(
                acc=pl.lit(0.0),
                function=lambda acc, expr: acc + expr,
                exprs=stress_columns,
            ).alias("_total_stress")
        else:
            total_stress = pl.lit(0.0).alias("_total_stress")
        lazy = lazy.with_columns(total_stress)

        names = frame.get_column("name").to_list()
        boost_lazy = pl.DataFrame({"name": [], "relationship_boost": []}).lazy()
        if not relationships.is_empty() and names:
            valid = relationships.filter(
                pl.col("source").is_in(names) & pl.col("target").is_in(names)
            )
            if not valid.is_empty():
                boost_lazy = (
                    valid.group_by("source")
                    .agg(pl.col("score").mean().alias("mean_score"))
                    .with_columns((pl.col("mean_score") / 200.0).alias("relationship_boost"))
                    .select(pl.col("source").alias("name"), "relationship_boost")
                    .lazy()
                )
        lazy = (
            lazy.join(boost_lazy, on="name", how="left")
            .with_columns(pl.col("relationship_boost").fill_null(0.0))
            .rename({"relationship_boost": "_relationship_boost"})
        )

        lazy = lazy.with_columns(
            (
                pl.col("morale")
                + pl.col("_relationship_boost") * 10.0
                - pl.col("_total_stress") * 6.0
            )
            .clip(lower_bound=0.0, upper_bound=100.0)
            .alias("morale")
        )

        drop_cols = ["_total_stress", "_relationship_boost"]
        for need_name in NeedName:
            prefix = need_name.value
            drop_cols.extend([f"{prefix}_satisfaction", f"{prefix}_stress"])

        return lazy.drop(drop_cols).collect()

    def _equilibrate_relationships(self, frame: pl.DataFrame) -> pl.DataFrame:
        names = list(self._members)
        if not names:
            return frame
        filtered = frame.filter(
            pl.col("source").is_in(names) & pl.col("target").is_in(names)
        )
        if filtered.is_empty():
            return filtered
        reverse = filtered.select(
            pl.col("target").alias("source"),
            pl.col("source").alias("target"),
            pl.col("score").alias("reverse_score"),
        )
        joined = filtered.join(reverse, on=["source", "target"], how="left")
        equilibrium = (
            pl.when(pl.col("reverse_score").is_null())
            .then(pl.col("score"))
            .otherwise((pl.col("score") + pl.col("reverse_score")) / 2.0)
        )
        return joined.with_columns(equilibrium.alias("score")).select(
            "source", "target", "score"
        )

    @staticmethod
    def _aggregate_impacts(
        names: Iterable[str],
        impacts: Mapping[str, TraitImpact],
        event: str,
    ) -> float:
        total = 0.0
        for name in names:
            impact = impacts.get(name)
            if impact is None:
                continue
            if event == "recruit":
                total += impact.recruit_morale
            elif event == "loss":
                total += impact.loss_morale
        return total


__all__ = [
    "Crew",
    "CrewLifecycleEvent",
    "CrewMember",
    "Need",
    "NeedName",
    "TraitImpact",
    "SkillCheckResult",
    "SkillType",
    "perform_skill_check",
    "team_skill_check",
]
