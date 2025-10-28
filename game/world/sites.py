"""Models describing persistent world sites and their state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class AttentionCurve:
    """Parameters describing how a site's attention changes over time."""

    base: float = 0.0
    growth: float = 0.0
    decay: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        """Serialize the curve parameters into a mapping."""

        return {"base": self.base, "growth": self.growth, "decay": self.decay}

    @staticmethod
    def from_dict(payload: Dict[str, float]) -> "AttentionCurve":
        """Create an :class:`AttentionCurve` instance from a mapping."""

        return AttentionCurve(
            base=float(payload.get("base", 0.0)),
            growth=float(payload.get("growth", 0.0)),
            decay=float(payload.get("decay", 0.0)),
        )


@dataclass
class Site:
    """State tracked for a point of interest in the overworld."""

    identifier: str
    exploration_percent: float = 0.0
    scavenged_percent: float = 0.0
    population: int = 0
    controlling_faction: str | None = None
    attention_curve: AttentionCurve = field(default_factory=AttentionCurve)

    def __post_init__(self) -> None:
        self.exploration_percent = self._clamp_percentage(self.exploration_percent)
        self.scavenged_percent = self._clamp_percentage(self.scavenged_percent)
        if self.population < 0:
            raise ValueError("population cannot be negative")
        if self.controlling_faction is not None:
            self.controlling_faction = str(self.controlling_faction)

    @staticmethod
    def _clamp_percentage(value: float) -> float:
        if not isinstance(value, (int, float)):
            raise TypeError("percentage values must be numeric")
        return max(0.0, min(float(value), 100.0))

    def record_exploration(self, amount: float) -> None:
        """Increase the exploration percentage by ``amount``."""

        self.exploration_percent = self._clamp_percentage(self.exploration_percent + amount)

    def record_scavenge(self, amount: float) -> None:
        """Increase the scavenged percentage by ``amount``."""

        self.scavenged_percent = self._clamp_percentage(self.scavenged_percent + amount)

    def to_dict(self) -> Dict[str, object]:
        """Serialize the site state into a JSON compatible mapping."""

        return {
            "identifier": self.identifier,
            "exploration_percent": self.exploration_percent,
            "scavenged_percent": self.scavenged_percent,
            "population": self.population,
            "controlling_faction": self.controlling_faction,
            "attention_curve": self.attention_curve.to_dict(),
        }

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "Site":
        """Create a :class:`Site` from a serialized mapping."""

        attention_payload = payload.get("attention_curve", {})
        if isinstance(attention_payload, AttentionCurve):
            attention_curve = attention_payload
        elif isinstance(attention_payload, dict):
            attention_curve = AttentionCurve.from_dict(
                {key: float(value) for key, value in attention_payload.items() if isinstance(key, str)}
            )
        else:
            attention_curve = AttentionCurve()
        identifier = payload.get("identifier")
        if identifier is None:
            raise ValueError("Serialized site payload missing 'identifier'")
        return Site(
            identifier=str(identifier),
            exploration_percent=float(payload.get("exploration_percent", 0.0)),
            scavenged_percent=float(payload.get("scavenged_percent", 0.0)),
            population=int(payload.get("population", 0)),
            controlling_faction=(
                None
                if payload.get("controlling_faction") is None
                else str(payload.get("controlling_faction"))
            ),
            attention_curve=attention_curve,
        )
