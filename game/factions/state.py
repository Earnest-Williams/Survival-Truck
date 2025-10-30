"""DataFrame-backed storage for factions and caravans."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from math import isnan

import polars as pl
from polars.type_aliases import PolarsDataType

_FACTION_SCHEMA: dict[str, PolarsDataType] = {"name": pl.String}
_KNOWN_SITE_SCHEMA: dict[str, PolarsDataType] = {"faction": pl.String, "site": pl.String}
_RESOURCE_SCHEMA: dict[str, PolarsDataType] = {
    "faction": pl.String,
    "resource": pl.String,
    "amount": pl.Float64,
}
_PREFERENCE_SCHEMA: dict[str, PolarsDataType] = {
    "faction": pl.String,
    "key": pl.String,
    "weight": pl.Float64,
}
_CARAVAN_SCHEMA: dict[str, PolarsDataType] = {
    "identifier": pl.String,
    "faction": pl.String,
    "location": pl.String,
    "days_until_move": pl.Int64,
    "route": pl.List(pl.String),
}
_CARAVAN_CARGO_SCHEMA: dict[str, PolarsDataType] = {
    "caravan": pl.String,
    "good": pl.String,
    "amount": pl.Int64,
}


def _to_list(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [str(item) for item in value]
    return []


def _is_nan(value: float) -> bool:
    try:
        return isnan(value)
    except TypeError:  # pragma: no cover - defensive
        return False


class FactionLedger:
    """Columnar store capturing all mutable faction state."""

    def __init__(self) -> None:
        self._factions = pl.DataFrame(schema=_FACTION_SCHEMA)
        self._known_sites = pl.DataFrame(schema=_KNOWN_SITE_SCHEMA)
        self._resources = pl.DataFrame(schema=_RESOURCE_SCHEMA)
        self._preferences = pl.DataFrame(schema=_PREFERENCE_SCHEMA)
        self._caravans = pl.DataFrame(schema=_CARAVAN_SCHEMA)
        self._caravan_cargo = pl.DataFrame(schema=_CARAVAN_CARGO_SCHEMA)

    # ------------------------------------------------------------------
    @classmethod
    def from_payload(cls, factions: Iterable[Mapping[str, object]] | None) -> FactionLedger:
        ledger = cls()
        for payload in factions or []:
            if not isinstance(payload, Mapping):
                raise TypeError("Faction payload must be a mapping")
            raw_name = payload.get("name")
            name = str(raw_name) if raw_name is not None else ""
            ledger.ensure_faction(name)
            known_sites = payload.get("known_sites")
            if isinstance(known_sites, Sequence) and not isinstance(known_sites, str | bytes):
                for site in known_sites:
                    ledger.add_known_site(name, str(site))
            resources = payload.get("resources")
            if isinstance(resources, Mapping):
                for resource, amount in resources.items():
                    if isinstance(amount, int | float | str):
                        try:
                            ledger.adjust_resource(name, str(resource), float(amount))
                        except ValueError:
                            continue
            preferences = payload.get("resource_preferences")
            if isinstance(preferences, Mapping):
                for key, weight in preferences.items():
                    if isinstance(weight, int | float | str):
                        try:
                            ledger.set_resource_preference(name, str(key), float(weight))
                        except ValueError:
                            continue
            caravans = payload.get("caravans")
            if isinstance(caravans, Mapping):
                for data in caravans.values():
                    if not isinstance(data, Mapping):
                        continue
                    raw_identifier = data.get("identifier")
                    identifier = str(raw_identifier) if raw_identifier is not None else ""
                    if not identifier:
                        continue
                    raw_location = data.get("location")
                    location = str(raw_location) if raw_location is not None else ""
                    ledger.register_caravan(name, identifier, location)
                    ledger.update_caravan_route(identifier, _to_list(data.get("route")))
                    days_raw = data.get("days_until_move")
                    days_until_move = int(days_raw) if isinstance(days_raw, int | str) else 0
                    ledger.update_caravan(
                        identifier,
                        days_until_move=days_until_move,
                        location=location,
                    )
                    cargo_payload = data.get("cargo")
                    if isinstance(cargo_payload, Mapping):
                        for good, amount in cargo_payload.items():
                            if isinstance(amount, int | float | str):
                                try:
                                    ledger.add_caravan_cargo(
                                        identifier, str(good), int(float(amount))
                                    )
                                except ValueError:
                                    continue
        return ledger

    # ------------------------------------------------------------------
    def clone(self) -> FactionLedger:
        other = FactionLedger()
        other._factions = self._factions.clone()
        other._known_sites = self._known_sites.clone()
        other._resources = self._resources.clone()
        other._preferences = self._preferences.clone()
        other._caravans = self._caravans.clone()
        other._caravan_cargo = self._caravan_cargo.clone()
        return other

    # ------------------------------------------------------------------
    def ensure_faction(self, name: str) -> None:
        if not name:
            return
        mask = pl.col("name") == name
        if self._factions.filter(mask).is_empty():
            self._factions = self._factions.vstack(
                pl.DataFrame([{"name": name}], schema=_FACTION_SCHEMA)
            )

    def iterate_factions(self) -> Iterator[FactionRecord]:
        for row in self._factions.iter_rows(named=True):
            yield FactionRecord(self, row["name"])

    def faction_record(self, name: str) -> FactionRecord:
        self.ensure_faction(name)
        return FactionRecord(self, name)

    # ------------------------------------------------------------------
    def add_known_site(self, faction: str, site: str) -> None:
        if not faction or not site:
            return
        mask = (pl.col("faction") == faction) & (pl.col("site") == site)
        if self._known_sites.filter(mask).is_empty():
            self._known_sites = self._known_sites.vstack(
                pl.DataFrame([{"faction": faction, "site": site}], schema=_KNOWN_SITE_SCHEMA)
            )

    def known_sites(self, faction: str) -> list[str]:
        matches = self._known_sites.filter(pl.col("faction") == faction)
        return list(matches.get_column("site")) if not matches.is_empty() else []

    # ------------------------------------------------------------------
    def adjust_resource(self, faction: str, resource: str, amount: float) -> None:
        if not faction or not resource or amount == 0:
            return
        mask = (pl.col("faction") == faction) & (pl.col("resource") == resource)
        matches = self._resources.filter(mask)
        total = float(amount)
        if not matches.is_empty():
            total += float(matches.get_column("amount")[0])
        self._resources = self._resources.filter(~mask)
        self._resources = self._resources.vstack(
            pl.DataFrame(
                [{"faction": faction, "resource": resource, "amount": total}],
                schema=_RESOURCE_SCHEMA,
            )
        )

    def resource_amount(self, faction: str, resource: str, default: float = 0.0) -> float:
        mask = (pl.col("faction") == faction) & (pl.col("resource") == resource)
        matches = self._resources.filter(mask)
        if matches.is_empty():
            return float(default)
        return float(matches.get_column("amount")[0])

    # ------------------------------------------------------------------
    def set_resource_preference(self, faction: str, key: str, weight: float) -> None:
        if not faction or not key:
            return
        mask = (pl.col("faction") == faction) & (pl.col("key") == key)
        self._preferences = self._preferences.filter(~mask)
        self._preferences = self._preferences.vstack(
            pl.DataFrame(
                [{"faction": faction, "key": key, "weight": float(weight)}],
                schema=_PREFERENCE_SCHEMA,
            )
        )

    def preference(self, faction: str, key: str, default: float = 1.0) -> float:
        mask = (pl.col("faction") == faction) & (pl.col("key") == key)
        matches = self._preferences.filter(mask)
        if matches.is_empty():
            return float(default)
        return float(matches.get_column("weight")[0])

    # ------------------------------------------------------------------
    def register_caravan(self, faction: str, identifier: str, location: str) -> CaravanRecord:
        if not identifier:
            raise ValueError("caravan identifier cannot be empty")
        self.ensure_faction(faction)
        mask = pl.col("identifier") == identifier
        self._caravans = self._caravans.filter(~mask)
        self._caravans = self._caravans.vstack(
            pl.DataFrame(
                [
                    {
                        "identifier": identifier,
                        "faction": faction,
                        "location": location,
                        "days_until_move": 0,
                        "route": [],
                    }
                ],
                schema=_CARAVAN_SCHEMA,
            )
        )
        return CaravanRecord(self, identifier)

    def remove_caravan(self, identifier: str) -> None:
        mask = pl.col("identifier") == identifier
        self._caravans = self._caravans.filter(~mask)
        self._caravan_cargo = self._caravan_cargo.filter(pl.col("caravan") != identifier)

    def caravans_for_faction(self, faction: str) -> dict[str, CaravanRecord]:
        matches = self._caravans.filter(pl.col("faction") == faction)
        handles: dict[str, CaravanRecord] = {}
        for row in matches.iter_rows(named=True):
            handles[row["identifier"]] = CaravanRecord(self, row["identifier"])
        return handles

    def caravan_row(self, identifier: str) -> Mapping[str, object]:
        match = self._caravans.filter(pl.col("identifier") == identifier)
        if match.is_empty():
            raise KeyError(identifier)
        return match.row(0, named=True)

    def update_caravan(self, identifier: str, **updates: object) -> None:
        if not updates:
            return
        mask = pl.col("identifier") == identifier
        columns = []
        for column, value in updates.items():
            columns.append(
                pl.when(mask)
                .then(pl.lit(value, dtype=self._caravans.schema[column]))
                .otherwise(pl.col(column))
                .alias(column)
            )
        self._caravans = self._caravans.with_columns(columns)

    def update_caravan_route(self, identifier: str, route: Sequence[str]) -> None:
        self.update_caravan(identifier, route=_to_list(route))

    # ------------------------------------------------------------------
    def add_caravan_cargo(self, identifier: str, good: str, amount: int) -> None:
        if amount <= 0:
            return
        mask = (pl.col("caravan") == identifier) & (pl.col("good") == good)
        matches = self._caravan_cargo.filter(mask)
        total = int(amount)
        if not matches.is_empty():
            total += int(matches.get_column("amount")[0])
        self._caravan_cargo = self._caravan_cargo.filter(~mask)
        self._caravan_cargo = self._caravan_cargo.vstack(
            pl.DataFrame(
                [{"caravan": identifier, "good": good, "amount": total}],
                schema=_CARAVAN_CARGO_SCHEMA,
            )
        )

    def consume_caravan_cargo(self, identifier: str) -> int:
        mask = pl.col("caravan") == identifier
        matches = self._caravan_cargo.filter(mask)
        if matches.is_empty():
            return 0
        total = int(matches.get_column("amount").sum())
        self._caravan_cargo = self._caravan_cargo.filter(~mask)
        return total

    def caravan_cargo(self, identifier: str) -> dict[str, int]:
        matches = self._caravan_cargo.filter(pl.col("caravan") == identifier)
        cargo: dict[str, int] = {}
        for row in matches.iter_rows(named=True):
            cargo[row["good"]] = int(row["amount"])
        return cargo

    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, dict[str, object]]:
        data: dict[str, dict[str, object]] = {}
        for faction in self.iterate_factions():
            data[faction.name] = faction.to_dict()
        return data


class FactionRecord:
    """Convenience wrapper for interacting with a faction row."""

    def __init__(self, ledger: FactionLedger, name: str) -> None:
        self.ledger = ledger
        self.name = name

    # ------------------------------------------------------------------
    @property
    def known_sites(self) -> list[str]:
        return self.ledger.known_sites(self.name)

    def add_known_site(self, site: str) -> None:
        self.ledger.add_known_site(self.name, site)

    # ------------------------------------------------------------------
    @property
    def caravans(self) -> dict[str, CaravanRecord]:
        return self.ledger.caravans_for_faction(self.name)

    def register_caravan(self, identifier: str, location: str) -> CaravanRecord:
        return self.ledger.register_caravan(self.name, identifier, location)

    def remove_caravan(self, identifier: str) -> None:
        self.ledger.remove_caravan(identifier)

    # ------------------------------------------------------------------
    def adjust_resource(self, resource: str, amount: float) -> None:
        self.ledger.adjust_resource(self.name, resource, amount)

    def resource_amount(self, resource: str, default: float = 0.0) -> float:
        return self.ledger.resource_amount(self.name, resource, default)

    def set_resource_preference(self, resource: str, weight: float) -> None:
        self.ledger.set_resource_preference(self.name, resource, weight)

    def preference_for(
        self,
        resource: str,
        *,
        category: str | None = None,
        default: float = 1.0,
    ) -> float:
        value = self.ledger.preference(self.name, resource, float("nan"))
        if not _is_nan(value):
            return value
        if category:
            category_value = self.ledger.preference(self.name, category, float("nan"))
            if not _is_nan(category_value):
                return category_value
            grouped = self.ledger.preference(self.name, f"category:{category}", float("nan"))
            if not _is_nan(grouped):
                return grouped
        fallback = self.ledger.preference(self.name, "default", float("nan"))
        if not _is_nan(fallback):
            return fallback
        return float(default)

    def preferred_trade_good(self, fallback: str = "supplies") -> str:
        prefs = self.ledger._preferences.filter(pl.col("faction") == self.name)
        best = fallback
        score = float("-inf")
        for row in prefs.iter_rows(named=True):
            key = row["key"]
            if key.startswith("category:"):
                continue
            weight = float(row["weight"])
            if weight > score:
                score = weight
                best = key
        if score == float("-inf"):
            return fallback
        return best

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "known_sites": self.known_sites,
            "resources": {
                row["resource"]: float(row["amount"])
                for row in self.ledger._resources.filter(pl.col("faction") == self.name).iter_rows(
                    named=True
                )
            },
            "resource_preferences": {
                row["key"]: float(row["weight"])
                for row in self.ledger._preferences.filter(
                    pl.col("faction") == self.name
                ).iter_rows(named=True)
            },
            "caravans": {
                identifier: handle.to_dict() for identifier, handle in self.caravans.items()
            },
        }


class CaravanRecord:
    """Interactive view for a single caravan stored in the ledger."""

    def __init__(self, ledger: FactionLedger, identifier: str) -> None:
        self.ledger = ledger
        self.identifier = identifier

    # ------------------------------------------------------------------
    @property
    def faction_name(self) -> str:
        return str(self.ledger.caravan_row(self.identifier)["faction"])

    @property
    def location(self) -> str:
        return str(self.ledger.caravan_row(self.identifier)["location"])

    @property
    def days_until_move(self) -> int:
        row = self.ledger.caravan_row(self.identifier)
        value = row.get("days_until_move")
        if isinstance(value, int | str):
            try:
                return int(value)
            except ValueError:  # pragma: no cover - defensive
                return 0
        return 0

    @property
    def route(self) -> list[str]:
        row = self.ledger.caravan_row(self.identifier)
        return _to_list(row.get("route"))

    # ------------------------------------------------------------------
    def plan_route(self, stops: Sequence[str]) -> None:
        self.ledger.update_caravan_route(self.identifier, stops)

    def advance_day(self) -> str | None:
        row = self.ledger.caravan_row(self.identifier)
        days_raw = row.get("days_until_move")
        if isinstance(days_raw, int | str):
            try:
                days = int(days_raw)
            except ValueError:  # pragma: no cover - defensive
                days = 0
        else:
            days = 0
        if days > 0:
            self.ledger.update_caravan(self.identifier, days_until_move=days - 1)
            return None
        route = _to_list(row.get("route"))
        location = str(row.get("location", ""))
        if route and route[0] == location:
            route.pop(0)
        if not route:
            return None
        next_site = str(route.pop(0))
        self.ledger.update_caravan(self.identifier, location=next_site, days_until_move=0)
        self.ledger.update_caravan_route(self.identifier, route)
        if next_site == location:
            return None
        return next_site

    def schedule_next_leg(self, edge_cost: int) -> None:
        self.ledger.update_caravan(self.identifier, days_until_move=max(0, int(edge_cost)))

    def unload_all_cargo(self) -> int:
        return self.ledger.consume_caravan_cargo(self.identifier)

    def add_cargo(self, good: str, amount: int) -> None:
        self.ledger.add_caravan_cargo(self.identifier, good, amount)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "location": self.location,
            "route": self.route,
            "days_until_move": self.days_until_move,
            "cargo": self.ledger.caravan_cargo(self.identifier),
        }


__all__ = ["CaravanRecord", "FactionLedger", "FactionRecord"]
