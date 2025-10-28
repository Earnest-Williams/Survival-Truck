"""Models describing persistent world sites and their state."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Mapping

from ..crew import SkillCheckResult, SkillType

__all__ = ["AttentionCurve", "Site", "SiteType"]


class SiteType(str, Enum):
    """Enumeration of canonical site archetypes."""

    CITY = "city"
    FARM = "farm"
    POWER_PLANT = "power_plant"
    CAMP = "camp"
    MILITARY_RUINS = "military_ruins"


@dataclass(frozen=True)
class AttentionCurve:
    """Gaussian parameters describing how a site's attention changes over time."""

    peak: float = 1.0
    mu: float = 50.0
    sigma: float = 15.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "peak", float(self.peak))
        object.__setattr__(self, "mu", float(self.mu))
        object.__setattr__(self, "sigma", float(self.sigma))
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")

    def to_dict(self) -> Dict[str, float]:
        """Serialize the curve parameters into a mapping."""

        return {"peak": self.peak, "mu": self.mu, "sigma": self.sigma}

    @staticmethod
    def from_dict(payload: Dict[str, float]) -> "AttentionCurve":
        """Create an :class:`AttentionCurve` instance from a mapping."""

        return AttentionCurve(
            peak=float(payload.get("peak", 1.0)),
            mu=float(payload.get("mu", 50.0)),
            sigma=float(payload.get("sigma", 15.0)),
        )

    def value_at(self, t: float) -> float:
        """Evaluate the Gaussian profile at ``t``."""

        exponent = -((float(t) - self.mu) ** 2) / (2 * self.sigma**2)
        return self.peak * math.exp(exponent)


@dataclass
class Site:
    """State tracked for a point of interest in the overworld."""

    identifier: str
    site_type: SiteType = SiteType.CAMP
    exploration_percent: float = 0.0
    scavenged_percent: float = 0.0
    population: int = 0
    controlling_faction: str | None = None
    attention_curve: AttentionCurve = field(default_factory=AttentionCurve)
    settlement_id: str | None = None
    connections: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.exploration_percent = self._clamp_percentage(self.exploration_percent)
        self.scavenged_percent = self._clamp_percentage(self.scavenged_percent)
        if self.population < 0:
            raise ValueError("population cannot be negative")
        if not isinstance(self.site_type, SiteType):
            try:
                self.site_type = SiteType(str(self.site_type))  # type: ignore[assignment]
            except ValueError as exc:  # pragma: no cover - defensive branch
                raise ValueError(f"Unknown site type: {self.site_type}") from exc
        if self.controlling_faction is not None:
            self.controlling_faction = str(self.controlling_faction)
        if not isinstance(self.attention_curve, AttentionCurve):
            if isinstance(self.attention_curve, Mapping):
                self.attention_curve = AttentionCurve.from_dict(self.attention_curve)  # type: ignore[assignment]
            else:
                self.attention_curve = AttentionCurve()  # type: ignore[assignment]
        if self.settlement_id is not None and not isinstance(self.settlement_id, str):
            raise TypeError("settlement_id must be a string or None")
        self.connections = self._normalise_connections(self.identifier, self.connections)

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
            "site_type": self.site_type.value,
            "exploration_percent": self.exploration_percent,
            "scavenged_percent": self.scavenged_percent,
            "population": self.population,
            "controlling_faction": self.controlling_faction,
            "attention_curve": self.attention_curve.to_dict(),
            "settlement_id": self.settlement_id,
            "connections": dict(self.connections),
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
            site_type=payload.get("site_type", SiteType.CAMP),
            exploration_percent=float(payload.get("exploration_percent", 0.0)),
            scavenged_percent=float(payload.get("scavenged_percent", 0.0)),
            population=int(payload.get("population", 0)),
            controlling_faction=(
                None
                if payload.get("controlling_faction") is None
                else str(payload.get("controlling_faction"))
            ),
            attention_curve=attention_curve,
            settlement_id=(
                None
                if payload.get("settlement_id") is None
                else str(payload.get("settlement_id"))
            ),
            connections=payload.get("connections", {}),
        )

    def connect(self, other: str, *, cost: float = 1.0) -> None:
        """Record a travel connection to ``other`` with ``cost``."""

        neighbour = str(other)
        if neighbour == self.identifier:
            return
        cost_value = float(cost)
        if cost_value < 0:
            raise ValueError("connection cost cannot be negative")
        self.connections[neighbour] = cost_value

    @staticmethod
    def _normalise_connections(identifier: str, data: Mapping[str, object] | object) -> Dict[str, float]:
        if not data:
            return {}
        if not isinstance(data, Mapping):
            raise TypeError("connections must be a mapping of site id to cost")
        normalised: Dict[str, float] = {}
        for neighbour, cost in data.items():
            key = str(neighbour)
            if not key:
                continue
            value = float(cost)
            if value < 0:
                raise ValueError("connection cost cannot be negative")
            if key == identifier:
                continue
            normalised[key] = value
        return normalised

    def resolve_scavenge_attempt(self, result: SkillCheckResult) -> float:
        """Apply the outcome of a scavenging skill check to this site.

        Returns the progress applied to :attr:`scavenged_percent`.
        """

        if result.skill != SkillType.SCAVENGING:
            raise ValueError("resolve_scavenge_attempt requires a scavenging skill result")
        base_progress = max(0.5, 4.0 + result.margin)
        intensity = max(0.05, self.attention_curve.value_at(self.scavenged_percent))
        progress = base_progress * intensity
        if not result.success:
            progress *= 0.25
        self.record_scavenge(progress)
        if result.success and self.population > 0:
            morale_boost = max(0, int(result.margin * max(1.0, intensity)))
            self.population = max(0, self.population + morale_boost)
        return progress

    def resolve_negotiation_attempt(self, result: SkillCheckResult, faction: str) -> float:
        """Apply the outcome of a negotiation attempt.

        Returns the change applied to the site's attention base.
        """

        if result.skill != SkillType.NEGOTIATION:
            raise ValueError("resolve_negotiation_attempt requires a negotiation skill result")
        sway = max(-5.0, min(5.0, result.margin / 2))
        curve = self.attention_curve
        influence = max(0.0, curve.value_at(self.exploration_percent))
        peak_delta = sway * 0.05 * (1.0 + influence)
        mu_delta = sway
        sigma_factor = 1.0
        margin_scale = min(0.5, abs(result.margin) * 0.02)
        if result.success:
            sigma_factor -= margin_scale
        else:
            sigma_factor += margin_scale
        sigma_factor = max(0.5, sigma_factor)
        self.attention_curve = AttentionCurve(
            peak=max(0.1, curve.peak + peak_delta),
            mu=max(0.0, min(100.0, curve.mu + mu_delta)),
            sigma=max(1.0, curve.sigma * sigma_factor),
        )
        if result.success:
            self.controlling_faction = faction
            self.population = max(self.population, int(10 + result.margin))
        else:
            self.population = max(0, int(self.population * 0.95))
        return sway
