"""DataFrame-backed state containers for dynamic world data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping

import polars as pl

from ..crew import SkillCheckResult, SkillType
from .sites import AttentionCurve, RiskCurve, Site, SiteType


_SITE_FRAME_SCHEMA: Dict[str, pl.datatypes.DataType] = {
    "identifier": pl.String,
    "site_type": pl.String,
    "exploration_percent": pl.Float64,
    "scavenged_percent": pl.Float64,
    "population": pl.Int64,
    "controlling_faction": pl.String,
    "attention_peak": pl.Float64,
    "attention_mu": pl.Float64,
    "attention_sigma": pl.Float64,
    "risk_maximum": pl.Float64,
    "risk_growth_rate": pl.Float64,
    "risk_midpoint": pl.Float64,
    "risk_floor": pl.Float64,
    "settlement_id": pl.String,
}

_CONNECTION_FRAME_SCHEMA: Dict[str, pl.datatypes.DataType] = {
    "source": pl.String,
    "target": pl.String,
    "cost": pl.Float64,
}


def _clamp_percentage(value: float) -> float:
    return max(0.0, min(float(value), 100.0))


@dataclass(slots=True)
class SiteRecord:
    """Lightweight view over a single row of the site state frame."""

    identifier: str
    site_type: SiteType
    exploration_percent: float
    scavenged_percent: float
    population: int
    controlling_faction: str | None
    attention: AttentionCurve
    risk: RiskCurve
    settlement_id: str | None


class SiteStateFrame:
    """Columnar store tracking all mutable site information."""

    def __init__(
        self,
        *,
        sites: pl.DataFrame | None = None,
        connections: pl.DataFrame | None = None,
    ) -> None:
        self._sites = (sites or pl.DataFrame(schema=_SITE_FRAME_SCHEMA)).with_columns(
            [
                pl.col("controlling_faction").cast(pl.String, strict=False),
                pl.col("settlement_id").cast(pl.String, strict=False),
            ]
        )
        self._connections = connections or pl.DataFrame(schema=_CONNECTION_FRAME_SCHEMA)

    # ------------------------------------------------------------------
    @classmethod
    def from_sites(
        cls, sites: Mapping[str, Site] | Iterable[Site] | None
    ) -> "SiteStateFrame":
        if not sites:
            return cls()
        if isinstance(sites, Mapping):
            iterable = sites.values()
        else:
            iterable = sites
        site_rows = []
        edge_rows = []
        for site in iterable:
            if not isinstance(site, Site):
                continue
            site_rows.append(
                {
                    "identifier": site.identifier,
                    "site_type": site.site_type.value,
                    "exploration_percent": float(site.exploration_percent),
                    "scavenged_percent": float(site.scavenged_percent),
                    "population": int(site.population),
                    "controlling_faction": site.controlling_faction or None,
                    "attention_peak": float(site.attention_curve.peak),
                    "attention_mu": float(site.attention_curve.mu),
                    "attention_sigma": float(site.attention_curve.sigma),
                    "risk_maximum": float(site.risk_curve.maximum),
                    "risk_growth_rate": float(site.risk_curve.growth_rate),
                    "risk_midpoint": float(site.risk_curve.midpoint),
                    "risk_floor": float(site.risk_curve.floor),
                    "settlement_id": site.settlement_id or None,
                }
            )
            for neighbour, cost in site.connections.items():
                if not neighbour or neighbour == site.identifier:
                    continue
                edge_rows.append(
                    {
                        "source": site.identifier,
                        "target": neighbour,
                        "cost": float(cost),
                    }
                )
        site_df = pl.DataFrame(site_rows, schema=_SITE_FRAME_SCHEMA)
        connection_df = pl.DataFrame(edge_rows, schema=_CONNECTION_FRAME_SCHEMA)
        return cls(sites=site_df, connections=connection_df)

    # ------------------------------------------------------------------
    def clone(self) -> "SiteStateFrame":
        return SiteStateFrame(sites=self._sites.clone(), connections=self._connections.clone())

    @property
    def sites(self) -> pl.DataFrame:
        return self._sites.clone()

    @property
    def connections(self) -> pl.DataFrame:
        return self._connections.clone()

    def has_site(self, identifier: str) -> bool:
        return not self._sites.filter(pl.col("identifier") == identifier).is_empty()

    def to_site(self, identifier: str) -> Site | None:
        match = self._sites.filter(pl.col("identifier") == identifier)
        if match.is_empty():
            return None
        row = match.row(0)
        attention = AttentionCurve(
            peak=row[self._sites.columns.index("attention_peak")],
            mu=row[self._sites.columns.index("attention_mu")],
            sigma=row[self._sites.columns.index("attention_sigma")],
        )
        risk = RiskCurve(
            maximum=row[self._sites.columns.index("risk_maximum")],
            growth_rate=row[self._sites.columns.index("risk_growth_rate")],
            midpoint=row[self._sites.columns.index("risk_midpoint")],
            floor=row[self._sites.columns.index("risk_floor")],
        )
        neighbours = (
            self._connections.filter(pl.col("source") == identifier)
            .select("target", "cost")
            .to_dict(as_series=False)
        )
        connections = {
            target: float(cost)
            for target, cost in zip(neighbours.get("target", []), neighbours.get("cost", []))
        }
        return Site(
            identifier=row[self._sites.columns.index("identifier")],
            site_type=SiteType(row[self._sites.columns.index("site_type")]),
            exploration_percent=row[self._sites.columns.index("exploration_percent")],
            scavenged_percent=row[self._sites.columns.index("scavenged_percent")],
            population=int(row[self._sites.columns.index("population")]),
            controlling_faction=row[self._sites.columns.index("controlling_faction")],
            attention_curve=attention,
            risk_curve=risk,
            settlement_id=row[self._sites.columns.index("settlement_id")],
            connections=connections,
        )

    def as_mapping(self) -> Dict[str, Site]:
        payload: Dict[str, Site] = {}
        for row in self._sites.iter_rows(named=True):
            attention = AttentionCurve(
                peak=row["attention_peak"],
                mu=row["attention_mu"],
                sigma=row["attention_sigma"],
            )
            risk = RiskCurve(
                maximum=row["risk_maximum"],
                growth_rate=row["risk_growth_rate"],
                midpoint=row["risk_midpoint"],
                floor=row["risk_floor"],
            )
            neighbours = (
                self._connections.filter(pl.col("source") == row["identifier"])
                .select("target", "cost")
                .to_dict(as_series=False)
            )
            connections = {
                target: float(cost)
                for target, cost in zip(neighbours.get("target", []), neighbours.get("cost", []))
            }
            payload[row["identifier"]] = Site(
                identifier=row["identifier"],
                site_type=SiteType(row["site_type"]),
                exploration_percent=row["exploration_percent"],
                scavenged_percent=row["scavenged_percent"],
                population=int(row["population"]),
                controlling_faction=row["controlling_faction"],
                attention_curve=attention,
                risk_curve=risk,
                settlement_id=row["settlement_id"],
                connections=connections,
            )
        return payload

    # ------------------------------------------------------------------
    def _update_site(self, identifier: str, values: MutableMapping[str, object]) -> None:
        if not values:
            return
        mask = pl.col("identifier") == identifier
        updates = []
        for column, value in values.items():
            updates.append(
                pl.when(mask).then(pl.lit(value, dtype=self._sites.schema[column])).otherwise(pl.col(column)).alias(column)
            )
        self._sites = self._sites.with_columns(updates)

    def record_exploration(self, identifier: str, amount: float) -> float:
        if not self.has_site(identifier):
            return 0.0
        column = "exploration_percent"
        current = self._sites.filter(pl.col("identifier") == identifier)[column][0]
        updated = _clamp_percentage(current + float(amount))
        self._update_site(identifier, {column: updated})
        return updated - current

    def record_scavenge(self, identifier: str, amount: float) -> float:
        if not self.has_site(identifier):
            return 0.0
        column = "scavenged_percent"
        current = self._sites.filter(pl.col("identifier") == identifier)[column][0]
        updated = _clamp_percentage(current + float(amount))
        self._update_site(identifier, {column: updated})
        return updated - current

    def apply_scavenge_result(self, identifier: str, result: SkillCheckResult) -> float:
        if result.skill != SkillType.SCAVENGING:
            raise ValueError("apply_scavenge_result requires a scavenging skill result")
        site_match = self._sites.filter(pl.col("identifier") == identifier)
        if site_match.is_empty():
            return 0.0
        row = site_match.row(0, named=True)
        base_progress = max(0.5, 4.0 + float(result.margin))
        attention = AttentionCurve(
            peak=row["attention_peak"],
            mu=row["attention_mu"],
            sigma=row["attention_sigma"],
        )
        intensity = max(0.05, attention.value_at(row["scavenged_percent"]))
        progress = base_progress * intensity
        if not result.success:
            progress *= 0.25
        scavenged = _clamp_percentage(row["scavenged_percent"] + progress)
        updates: Dict[str, object] = {"scavenged_percent": scavenged}
        population = int(row["population"])
        if result.success and population > 0:
            morale_boost = max(0, int(result.margin * max(1.0, intensity)))
            updates["population"] = max(0, population + morale_boost)
        self._update_site(identifier, updates)
        return progress

    def apply_negotiation_result(self, identifier: str, result: SkillCheckResult, faction: str) -> float:
        if result.skill != SkillType.NEGOTIATION:
            raise ValueError("apply_negotiation_result requires a negotiation skill result")
        site_match = self._sites.filter(pl.col("identifier") == identifier)
        if site_match.is_empty():
            return 0.0
        row = site_match.row(0, named=True)
        sway = max(-5.0, min(5.0, result.margin / 2))
        curve = AttentionCurve(
            peak=row["attention_peak"],
            mu=row["attention_mu"],
            sigma=row["attention_sigma"],
        )
        influence = max(0.0, curve.value_at(row["exploration_percent"]))
        peak_delta = sway * 0.05 * (1.0 + influence)
        mu_delta = sway
        sigma_factor = 1.0
        margin_scale = min(0.5, abs(result.margin) * 0.02)
        if result.success:
            sigma_factor -= margin_scale
        else:
            sigma_factor += margin_scale
        sigma_factor = max(0.5, sigma_factor)
        new_curve = AttentionCurve(
            peak=max(0.1, curve.peak + peak_delta),
            mu=max(0.0, min(100.0, curve.mu + mu_delta)),
            sigma=max(1.0, curve.sigma * sigma_factor),
        )
        updates: Dict[str, object] = {
            "attention_peak": new_curve.peak,
            "attention_mu": new_curve.mu,
            "attention_sigma": new_curve.sigma,
        }
        population = int(row["population"])
        if result.success:
            updates["controlling_faction"] = faction
            updates["population"] = max(population, int(10 + result.margin))
        else:
            updates["population"] = max(0, int(population * 0.95))
        self._update_site(identifier, updates)
        return sway

    def set_connection(self, origin: str, target: str, cost: float) -> None:
        if origin == target:
            return
        self._connections = self._connections.filter(
            ~((pl.col("source") == origin) & (pl.col("target") == target))
        )
        self._connections = self._connections.vstack(
            pl.DataFrame(
                [
                    {
                        "source": origin,
                        "target": target,
                        "cost": float(cost),
                    }
                ],
                schema=_CONNECTION_FRAME_SCHEMA,
            )
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "sites": self._sites.clone(),
            "connections": self._connections.clone(),
        }


__all__ = ["SiteRecord", "SiteStateFrame"]
