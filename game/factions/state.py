"""DataFrame-backed storage for factions and caravans.

This module has been adapted from the upstream project to include an
additional reputation store per faction. Reputation represents
how each non-player faction views the player character. Positive values
mean a friendly or allied stance, negative values indicate hostility,
and zero is neutral. Reputation is distinct from inter-faction
diplomacy (handled in :mod:`game.factions`), and is used to modify
prices, access permissions and mission availability on the player
side.

The original code is licensed under the project's terms.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
import random
from math import isnan
from typing import Optional

import polars as pl
from polars._typing import PolarsDataType

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

# New schema for storing player reputation values per faction.
_REPUTATION_SCHEMA: dict[str, PolarsDataType] = {
    "faction": pl.String,
    "value": pl.Float64,
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
    """Columnar store capturing all mutable faction state.

    This class manages multiple table-like structures for faction-related data. It now
    includes a dedicated reputation store, enabling factions to track the player's
    standing independently of diplomatic relations between factions. Reputation values
    are clamped between -100 and 100 and decay towards zero over time only if
    explicitly invoked via :meth:`decay_reputations`. No automatic decay occurs.
    """

    def __init__(self) -> None:
        self._factions = pl.DataFrame(schema=_FACTION_SCHEMA)
        self._known_sites = pl.DataFrame(schema=_KNOWN_SITE_SCHEMA)
        self._resources = pl.DataFrame(schema=_RESOURCE_SCHEMA)
        self._preferences = pl.DataFrame(schema=_PREFERENCE_SCHEMA)
        self._caravans = pl.DataFrame(schema=_CARAVAN_SCHEMA)
        self._caravan_cargo = pl.DataFrame(schema=_CARAVAN_CARGO_SCHEMA)
        # Reputation table: one row per faction representing player standing.
        self._reputations = pl.DataFrame(schema=_REPUTATION_SCHEMA)
        # Memory events store. Each entry tracks a discrete interaction between the
        # player and a faction, with an associated impact and decay rate. See
        # :meth:`record_memory` for details. The ``day`` column stores the
        # absolute day when the event occurred, and ``impact`` is a signed
        # magnitude of its effect on the faction's sentiment. ``decay_rate`` is
        # the fraction of the impact that is lost each day.
        self._memories = pl.DataFrame(
            schema={
                "faction": pl.String,
                "event": pl.String,
                "impact": pl.Float64,
                "day": pl.Int64,
                "decay_rate": pl.Float64,
            }
        )

        # Ideology table: tracks each faction's guiding ideology. Ideologies
        # influence trade preferences, diplomatic tendencies and AI behaviour.
        # If no ideology is recorded for a faction, it defaults to "neutral".
        self._ideologies = pl.DataFrame(
            schema={"faction": pl.String, "ideology": pl.String}
        )

        # Ideology weight table: captures how strongly each faction
        # aligns with every available ideology.  The weights in each
        # row sum to approximately 1.0.  When a faction is created
        # without specifying its ideology, we initialise it with a
        # one-hot vector (weight 1.0 for the default ideology, 0.0 for
        # others).  Over time, weights can be adjusted to model
        # nuanced ideological blends.  This table has columns:
        #   - faction: faction name
        #   - ideology: the ideology name
        #   - weight: a float between 0.0 and 1.0
        self._ideology_weights = pl.DataFrame(
            schema={"faction": pl.String, "ideology": pl.String, "weight": pl.Float64}
        )

        # Trait table: records behavioural traits for each faction.  Each
        # trait has an associated numeric value between 0 and 1
        # expressing how strongly the faction exhibits that trait.  A
        # higher value means the trait has greater influence on the
        # faction's decisions.  If no traits are recorded for a
        # faction, default values (typically zero) are assumed.
        self._traits = pl.DataFrame(
            schema={"faction": pl.String, "trait": pl.String, "value": pl.Float64}
        )

        # Define a set of default traits.  Traits allow factions to
        # exhibit nuanced behaviours beyond ideology.  Aggressive
        # factions raid more readily, cautious factions avoid conflict,
        # greedy factions demand tribute, benevolent factions offer aid,
        # and expansionist factions seek alliances and coalitions.
        self.DEFAULT_TRAITS: tuple[str, ...] = (
            "aggressive",
            "cautious",
            "greedy",
            "benevolent",
            "expansionist",
        )
        # Define a tuple of default ideologies. When a new faction is created
        # without specifying its ideology, one of these will be assigned
        # deterministically based on its name.
        self.DEFAULT_IDEOLOGIES: tuple[str, ...] = (
            # Core ideologies guiding faction behaviour.  Additional
            # ideologies beyond the original three have been added to
            # diversify NPC motivations.  Technocratic factions value
            # knowledge and precision; militaristic factions prize
            # strength and security; tribalist factions favour
            # tradition and community; mercantile factions pursue
            # wealth and commerce; religious factions are driven by
            # faith and spirituality.  Scientific factions prioritise
            # research, salvage and technological progress, while
            # nomadic factions emphasise mobility and independence.  When
            # a new faction is created without a specified ideology, the
            # name's hash is used to select one of these defaults.
            "technocratic",
            "militaristic",
            "tribalist",
            "mercantile",
            "religious",
            "scientific",
            "nomadic",
        )

        # Resource preferences keyed by ideology. When a faction is assigned
        # an ideology, these preferences will be applied automatically if
        # no explicit preferences exist. Keys represent resource names or
        # item categories understood by the game's economy.
        self.IDEOLOGY_RESOURCE_PREFS: dict[str, dict[str, float]] = {
            "technocratic": {
                "electronics": 2.0,
                "fuel": 1.5,
                "supplies": 0.5,
            },
            "militaristic": {
                "weapons": 2.0,
                "ammo": 1.5,
                "fuel": 1.2,
            },
            "tribalist": {
                "food": 2.0,
                "water": 1.5,
                "supplies": 1.0,
            },
            # Merchants place high value on trade goods, wealth and fuel
            "mercantile": {
                "trade_goods": 2.0,
                "wealth": 1.5,
                "electronics": 1.0,
                "fuel": 1.0,
            },
            # Religious factions favour basic necessities and perhaps
            # relics (modelled as "relics" resource) over material wealth.
            "religious": {
                "food": 1.5,
                "water": 1.5,
                "supplies": 1.0,
                "relics": 2.0,
            },
            # Scientific factions value research materials, salvage and
            # electronics.  They may also prioritise medical supplies.
            "scientific": {
                "electronics": 2.0,
                "salvage": 1.5,
                "medical_supplies": 1.5,
                "fuel": 1.0,
            },
            # Nomadic factions favour portable goods and basic sustenance.
            "nomadic": {
                "fuel": 1.5,
                "food": 1.5,
                "water": 1.5,
                "supplies": 1.0,
                "trade_goods": 0.8,
            },
        }

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
            # Initialise reputation from payload, else defaults to neutral.
            if name and ledger._reputations.filter(pl.col("faction") == name).is_empty():
                ledger._reputations = ledger._reputations.vstack(
                    pl.DataFrame([{"faction": name, "value": 0.0}], schema=_REPUTATION_SCHEMA)
                )
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
        other._reputations = self._reputations.clone()
        other._ideologies = self._ideologies.clone()
        # Copy default ideologies tuple
        other.DEFAULT_IDEOLOGIES = tuple(self.DEFAULT_IDEOLOGIES)
        # Copy ideology weights
        other._ideology_weights = self._ideology_weights.clone()
        other._traits = self._traits.clone()
        other.DEFAULT_TRAITS = tuple(self.DEFAULT_TRAITS)
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
        # Make sure reputation entry exists for this faction
        if self._reputations.filter(pl.col("faction") == name).is_empty():
            self._reputations = self._reputations.vstack(
                pl.DataFrame([{"faction": name, "value": 0.0}], schema=_REPUTATION_SCHEMA)
            )

        # Assign a default ideology if none exists for this faction. We choose
        # a deterministic index based on the faction name to ensure the same
        # faction receives the same default ideology across runs. New
        # factions created dynamically (e.g. via schisms) may specify
        # their own ideology explicitly via set_ideology().
        if self._ideologies.filter(pl.col("faction") == name).is_empty():
            # Compute a stable index into the DEFAULT_IDEOLOGIES tuple.
            try:
                idx = abs(hash(name)) % len(self.DEFAULT_IDEOLOGIES)
            except Exception:
                idx = 0
            default_ideology = self.DEFAULT_IDEOLOGIES[idx] if self.DEFAULT_IDEOLOGIES else "neutral"
            self._ideologies = self._ideologies.vstack(
                pl.DataFrame(
                    [{"faction": name, "ideology": default_ideology}],
                    schema={"faction": pl.String, "ideology": pl.String},
                )
            )
            # Initialise ideology weights: one-hot vector for default ideology
            # We create rows for all default ideologies to ensure the
            # table is complete; weight is 1.0 for the default and 0.0
            # for all others.
            weight_rows = []
            for ide in self.DEFAULT_IDEOLOGIES:
                weight_rows.append({
                    "faction": name,
                    "ideology": str(ide),
                    "weight": 1.0 if ide == default_ideology else 0.0,
                })
            self._ideology_weights = self._ideology_weights.vstack(
                pl.DataFrame(weight_rows, schema={"faction": pl.String, "ideology": pl.String, "weight": pl.Float64})
            )

            # Initialise behavioural traits for the new faction.  We
            # assign random values to each trait using a deterministic
            # pseudorandom sequence derived from the faction name.  This
            # ensures reproducibility across runs.  Traits are scaled
            # between 0.0 and 1.0.  Factions can later adjust these
            # values via game events or scripts.
            try:
                seed_val = abs(hash(name))
            except Exception:
                seed_val = 0
            rng = random.Random(seed_val)
            trait_rows = []
            for trait in self.DEFAULT_TRAITS:
                trait_rows.append({
                    "faction": name,
                    "trait": trait,
                    "value": rng.random(),
                })
            self._traits = self._traits.vstack(
                pl.DataFrame(trait_rows, schema={"faction": pl.String, "trait": pl.String, "value": pl.Float64})
            )

    def iterate_factions(self) -> Iterator[FactionRecord]:
        for row in self._factions.iter_rows(named=True):
            yield FactionRecord(self, row["name"])

    def faction_record(self, name: str) -> FactionRecord:
        self.ensure_faction(name)
        return FactionRecord(self, name)

    # ------------------------------------------------------------------
    def set_ideology(self, faction: str, ideology: str) -> None:
        """Set the ideology for a faction.

        This method records or updates the ideology associated with
        ``faction``. Ideologies guide AI behaviour and diplomatic
        tendencies. Passing an empty ideology will remove any existing
        entry for the faction.
        """
        if not faction:
            return
        # Remove any existing entry for this faction.
        self._ideologies = self._ideologies.filter(pl.col("faction") != faction)
        if ideology:
            self._ideologies = self._ideologies.vstack(
                pl.DataFrame([
                    {"faction": faction, "ideology": str(ideology)},
                ], schema={"faction": pl.String, "ideology": pl.String})
            )

        # Reset ideology weights for the faction: assign weight 1.0
        # to the specified ideology (if provided) and 0.0 to all
        # others in DEFAULT_IDEOLOGIES. If ideology is empty or
        # unknown, weights become uniform (neutral).  Remove any
        # existing weight rows for the faction first.
        self._ideology_weights = self._ideology_weights.filter(pl.col("faction") != faction)
        if ideology:
            rows = []
            for ide in self.DEFAULT_IDEOLOGIES:
                rows.append({
                    "faction": faction,
                    "ideology": str(ide),
                    "weight": 1.0 if ide == ideology else 0.0,
                })
            self._ideology_weights = self._ideology_weights.vstack(
                pl.DataFrame(rows, schema={"faction": pl.String, "ideology": pl.String, "weight": pl.Float64})
            )
        else:
            # If no ideology provided, assign equal weights across all
            # default ideologies (neutral stance).
            if self.DEFAULT_IDEOLOGIES:
                equal = 1.0 / len(self.DEFAULT_IDEOLOGIES)
                rows = []
                for ide in self.DEFAULT_IDEOLOGIES:
                    rows.append({
                        "faction": faction,
                        "ideology": str(ide),
                        "weight": equal,
                    })
                self._ideology_weights = self._ideology_weights.vstack(
                    pl.DataFrame(rows, schema={"faction": pl.String, "ideology": pl.String, "weight": pl.Float64})
                )

        # Apply default resource preferences associated with this ideology if
        # the faction has not already specified any. Preferences set via
        # payloads or gameplay take precedence over defaults.
        try:
            prefs_exist = not self._preferences.filter(pl.col("faction") == faction).is_empty()
            if ideology and not prefs_exist:
                pref_map = self.IDEOLOGY_RESOURCE_PREFS.get(str(ideology), {})
                for resource, weight in pref_map.items():
                    try:
                        self.set_resource_preference(faction, resource, float(weight))
                    except Exception:
                        continue
        except Exception:
            # Ignore preference assignment errors
            pass

    def ideology(self, faction: str, default: str = "neutral") -> str:
        """Return the ideology for a faction.

        If no ideology is recorded, return ``default``. The default
        ideology is ``"neutral"`` if not provided.
        """
        if not faction:
            return str(default)
        matches = self._ideologies.filter(pl.col("faction") == faction)
        if matches.is_empty():
            return str(default)
        # Derive ideology from the weight table if available.  We
        # compute the ideology with the highest weight; if weights are
        # missing, fall back to the stored discrete ideology.  Ties
        # favour the existing discrete value.
        try:
            weight_matches = self._ideology_weights.filter(pl.col("faction") == faction)
            if not weight_matches.is_empty():
                # Compute the ideology with maximum weight
                max_idx = float("-inf")
                top_ideology = None
                for row in weight_matches.iter_rows(named=True):
                    ide = row["ideology"]
                    wt = float(row["weight"])
                    if top_ideology is None or wt > max_idx:
                        top_ideology = str(ide)
                        max_idx = wt
                if top_ideology is not None:
                    return top_ideology
        except Exception:
            pass
        # Fallback to stored ideology value
        value = matches.get_column("ideology")[0]
        return str(value)

    def ideology_weights(self, faction: str) -> dict[str, float]:
        """Return the ideology weight distribution for a faction.

        The returned mapping contains one entry per ideology in
        ``DEFAULT_IDEOLOGIES``. If no weights are stored, a uniform
        distribution is returned. We normalise weights so that their
        sum is 1.0 to avoid drift due to rounding errors.
        """
        if not faction:
            return {ide: 1.0 / len(self.DEFAULT_IDEOLOGIES) for ide in self.DEFAULT_IDEOLOGIES} if self.DEFAULT_IDEOLOGIES else {}
        matches = self._ideology_weights.filter(pl.col("faction") == faction)
        if matches.is_empty() or not self.DEFAULT_IDEOLOGIES:
            # Uniform default
            return {ide: 1.0 / len(self.DEFAULT_IDEOLOGIES) for ide in self.DEFAULT_IDEOLOGIES}
        weights: dict[str, float] = {ide: 0.0 for ide in self.DEFAULT_IDEOLOGIES}
        total = 0.0
        for row in matches.iter_rows(named=True):
            ide = str(row["ideology"])
            wt = float(row["weight"])
            weights[ide] = wt
            total += wt
        # Normalize
        if total > 0:
            for key in weights:
                weights[key] = weights[key] / total
        else:
            # Uniform if total is zero
            count = len(weights)
            for key in weights:
                weights[key] = 1.0 / count
        return weights

    def adjust_ideology_weight(self, faction: str, ideology: str, delta: float) -> None:
        """Incrementally adjust a faction's ideology weights.

        This method increases the weight for ``ideology`` by a fraction
        ``delta`` of the remaining distance to 1.0 and proportionally
        decreases weights of all other ideologies.  This ensures that
        the weights remain normalised and that small adjustments
        gradually move the faction along an ideological spectrum.

        Args:
            faction: The faction whose weights to update.
            ideology: The ideology whose weight should be increased.
            delta: A number between 0 and 1 representing the fraction
                of the difference towards the target ideology.
        """
        if not faction or ideology not in self.DEFAULT_IDEOLOGIES or delta <= 0:
            return
        # Fetch current weights or initialize uniform distribution
        weights = self.ideology_weights(faction)
        # Compute incremental changes
        target_weight = weights.get(ideology, 0.0)
        # The amount by which the target ideology will increase
        increase = delta * (1.0 - target_weight)
        # Subtract from others proportionally
        num_other = len(self.DEFAULT_IDEOLOGIES) - 1
        if num_other <= 0:
            return
        decrease_each = increase / num_other
        updated = {}
        for ide, wt in weights.items():
            if ide == ideology:
                updated[ide] = wt + increase
            else:
                updated[ide] = max(0.0, wt - decrease_each)
        # Normalise again to avoid rounding issues
        total = sum(updated.values())
        if total > 0:
            for ide in updated:
                updated[ide] = updated[ide] / total
        # Persist back to the DataFrame: remove existing entries for the faction
        self._ideology_weights = self._ideology_weights.filter(pl.col("faction") != faction)
        rows = []
        for ide, wt in updated.items():
            rows.append({"faction": faction, "ideology": ide, "weight": wt})
        self._ideology_weights = self._ideology_weights.vstack(
            pl.DataFrame(rows, schema={"faction": pl.String, "ideology": pl.String, "weight": pl.Float64})
        )

    # ------------------------------------------------------------------
    def set_ideology_weights(self, faction: str, weights: Mapping[str, float]) -> None:
        """Replace a faction's ideology weight distribution.

        The provided ``weights`` mapping should contain entries for each
        ideology present in ``DEFAULT_IDEOLOGIES``.  Values will be
        normalised so that their sum equals 1.0.  Existing weights for
        the faction are removed and replaced by the new distribution.

        Args:
            faction: The name of the faction to update.
            weights: A mapping from ideology names to weight values.
        """
        if not faction or not weights:
            return
        # Ensure all ideologies are present; missing keys get zero.
        vals: dict[str, float] = {}
        total = 0.0
        for ide in self.DEFAULT_IDEOLOGIES:
            try:
                wt = float(weights.get(ide, 0.0))
            except Exception:
                wt = 0.0
            vals[ide] = max(0.0, wt)
            total += vals[ide]
        # Normalise if total > 0; otherwise assign uniform distribution.
        if total > 0.0:
            for ide in vals:
                vals[ide] = vals[ide] / total
        else:
            count = len(self.DEFAULT_IDEOLOGIES)
            if count:
                for ide in vals:
                    vals[ide] = 1.0 / count
        # Replace existing rows for this faction
        self._ideology_weights = self._ideology_weights.filter(pl.col("faction") != faction)
        rows = [
            {"faction": faction, "ideology": ide, "weight": wt}
            for ide, wt in vals.items()
        ]
        if rows:
            self._ideology_weights = self._ideology_weights.vstack(
                pl.DataFrame(rows, schema={"faction": pl.String, "ideology": pl.String, "weight": pl.Float64})
            )

    # ------------------------------------------------------------------
    def set_trait(self, faction: str, trait: str, value: float) -> None:
        """Set a behavioural trait for a faction.

        Traits represent behavioural tendencies (e.g. aggression,
        caution) and are stored as floats between 0 and 1.  If the
        trait is not among the ``DEFAULT_TRAITS``, this call has no
        effect.  Existing values are overwritten.
        """
        if not faction or trait not in self.DEFAULT_TRAITS:
            return
        # Clamp value between 0 and 1
        try:
            val = max(0.0, min(1.0, float(value)))
        except Exception:
            return
        # Remove existing row
        self._traits = self._traits.filter(~((pl.col("faction") == faction) & (pl.col("trait") == trait)))
        # Append new value
        self._traits = self._traits.vstack(
            pl.DataFrame([{"faction": faction, "trait": trait, "value": val}], schema={"faction": pl.String, "trait": pl.String, "value": pl.Float64})
        )

    def get_trait(self, faction: str, trait: str, default: float = 0.0) -> float:
        """Return the value of a behavioural trait for a faction.

        If the trait is not recorded or invalid, return ``default``.
        """
        if not faction or trait not in self.DEFAULT_TRAITS:
            return float(default)
        matches = self._traits.filter((pl.col("faction") == faction) & (pl.col("trait") == trait))
        if matches.is_empty():
            return float(default)
        try:
            return float(matches.get_column("value")[0])
        except Exception:
            return float(default)

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
    def adjust_reputation(self, faction: str, delta: float) -> float:
        """Adjust the player's reputation with a faction by ``delta`` and return the new value.

        Reputation values are kept within the range [-100, 100]. If the faction does not
        exist, it will be created with a neutral reputation before applying the delta.
        """
        if not faction:
            return 0.0
        self.ensure_faction(faction)
        mask = pl.col("faction") == faction
        matches = self._reputations.filter(mask)
        current = float(matches.get_column("value")[0]) if not matches.is_empty() else 0.0
        updated = max(-100.0, min(100.0, current + float(delta)))
        self._reputations = self._reputations.filter(~mask)
        self._reputations = self._reputations.vstack(
            pl.DataFrame(
                [{"faction": faction, "value": updated}],
                schema=_REPUTATION_SCHEMA,
            )
        )
        return updated

    def reputation(self, faction: str, default: float = 0.0) -> float:
        """Return the player's reputation with a faction or ``default`` if none exists."""
        if not faction:
            return float(default)
        matches = self._reputations.filter(pl.col("faction") == faction)
        if matches.is_empty():
            return float(default)
        return float(matches.get_column("value")[0])

    def decay_reputations(self, decay_rate: float = 0.1) -> None:
        """Move all reputations towards zero by ``decay_rate`` points.

        This method is not called automatically; it should be invoked by game logic
        when appropriate (e.g. at the end of a season).
        """
        updated_rows = []
        for row in self._reputations.iter_rows(named=True):
            name = row["faction"]
            value = float(row["value"])
            if abs(value) <= decay_rate:
                updated = 0.0
            elif value > 0:
                updated = max(0.0, value - decay_rate)
            else:
                updated = min(0.0, value + decay_rate)
            updated_rows.append({"faction": name, "value": updated})
        self._reputations = pl.DataFrame(updated_rows, schema=_REPUTATION_SCHEMA)

    # ------------------------------------------------------------------
    def record_memory(
        self,
        faction: str,
        event: str,
        impact: float,
        day: int,
        decay_rate: float = 0.05,
    ) -> None:
        """Record a discrete memory event for a faction.

        Parameters
        ----------
        faction: str
            The name of the faction affected by the event.
        event: str
            A short description of the event (e.g., "spring famine aid").
        impact: float
            The signed impact on the faction's sentiment; positive numbers
            represent helpful acts and negative numbers represent hostile acts.
        day: int
            The absolute day number when the event occurred. The turn engine
            should supply this value.
        decay_rate: float, optional
            The fraction of the event's impact that decays each day. A value
            between 0 and 1.0; lower values make memories linger longer.

        Each call appends a new memory record. Memories are not merged or
        deduplicated; multiple events on the same day will accumulate.
        """
        if not faction or impact == 0.0:
            return
        self.ensure_faction(faction)
        self._memories = self._memories.vstack(
            pl.DataFrame(
                [
                    {
                        "faction": faction,
                        "event": event,
                        "impact": float(impact),
                        "day": int(day),
                        "decay_rate": float(decay_rate),
                    }
                ],
                schema=self._memories.schema,
            )
        )

    def memory_effect(self, faction: str, current_day: int) -> float:
        """Compute the cumulative memory effect for a faction.

        The effect is the sum over all recorded events of the surviving
        impact. For an event recorded at day ``d`` with impact ``I`` and
        decay rate ``r``, the surviving impact on ``current_day`` is
        ``max(0, I * (1 - r) ** (current_day - d))``. This exponential
        decay ensures that events gradually fade over time. Events whose
        surviving impact would be zero are ignored.

        Parameters
        ----------
        faction: str
            The faction for which to compute the memory effect.
        current_day: int
            The current absolute day number.

        Returns
        -------
        float
            The sum of surviving impacts for all events associated with the
            faction.
        """
        if not faction:
            return 0.0
        mask = pl.col("faction") == faction
        events = self._memories.filter(mask)
        if events.is_empty():
            return 0.0
        total = 0.0
        for row in events.iter_rows(named=True):
            impact = float(row["impact"])
            day = int(row["day"])
            rate = float(row["decay_rate"])
            elapsed = max(0, current_day - day)
            # Surviving impact after elapsed days
            surviving = impact * ((1.0 - rate) ** elapsed)
            if abs(surviving) <= 0.0001:
                continue
            total += surviving
        return total

    def prune_memories(self, current_day: int, threshold: float = 0.0001) -> None:
        """Remove memory events whose surviving impact has decayed below a threshold.

        This method iterates over all stored memories and removes those whose
        impact would be negligible on the given ``current_day``. Use this
        periodically to prevent unbounded growth of the memory table.
        """
        remaining_rows = []
        for row in self._memories.iter_rows(named=True):
            impact = float(row["impact"])
            day = int(row["day"])
            rate = float(row["decay_rate"])
            elapsed = max(0, current_day - day)
            surviving = impact * ((1.0 - rate) ** elapsed)
            if abs(surviving) > threshold:
                remaining_rows.append(row)
        if remaining_rows:
            self._memories = pl.DataFrame(remaining_rows, schema=self._memories.schema)
        else:
            # Reset to empty DataFrame with original schema
            self._memories = pl.DataFrame(schema=self._memories.schema)

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
    @property
    def reputation(self) -> float:
        """Return the player's current reputation with this faction."""
        return self.ledger.reputation(self.name, 0.0)

    def adjust_reputation(self, delta: float) -> float:
        """Adjust the player's reputation with this faction by ``delta`` and return the new value."""
        return self.ledger.adjust_reputation(self.name, delta)

    # ------------------------------------------------------------------
    @property
    def ideology(self) -> str:
        """Return the faction's ideology.

        Ideologies influence trade preferences and diplomatic behaviour. If
        none has been set explicitly, a default value (often "neutral") is
        returned.
        """
        return self.ledger.ideology(self.name, "neutral")

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
            # Expose reputation for persistence and debugging
            "reputation": self.reputation,
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