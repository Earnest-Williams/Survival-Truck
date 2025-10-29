"""Hex-based world map utilities with chunk streaming and biome noise."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, ClassVar, Dict, Iterator, Mapping, MutableMapping, Tuple

from opensimplex import OpenSimplex

from ..rng import WorldRandomness
from ..sites import AttentionCurve, Site, SiteType


class BiomeType(str, Enum):
    """Canonical biome classifications used by the overworld."""

    BARREN = "barren"
    SCRUBLAND = "scrubland"
    FOREST = "forest"
    HIGHLAND = "highland"
    WATER = "water"


@dataclass(frozen=True)
class HexCoord:
    """Axial hex-grid coordinate."""

    q: int
    r: int

    @property
    def s(self) -> int:
        return -self.q - self.r

    def translate(self, dq: int, dr: int) -> "HexCoord":
        return HexCoord(self.q + dq, self.r + dr)

    def distance_to(self, other: "HexCoord") -> int:
        return max(abs(self.q - other.q), abs(self.r - other.r), abs(self.s - other.s))

    DIRECTIONS: ClassVar[Tuple[Tuple[int, int], ...]] = (
        (1, 0),
        (1, -1),
        (0, -1),
        (-1, 0),
        (-1, 1),
        (0, 1),
    )

    def neighbor(self, index: int) -> "HexCoord":
        direction = self.DIRECTIONS[index % 6]
        return self.translate(*direction)

    def to_chunk(self, chunk_size: int) -> "ChunkCoord":
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        return ChunkCoord(self.q // chunk_size, self.r // chunk_size)

    def offset_within(self, chunk_size: int) -> Tuple[int, int]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        return self.q % chunk_size, self.r % chunk_size


@dataclass(frozen=True)
class ChunkCoord:
    """Coordinate of a chunk in the chunk grid."""

    q: int
    r: int

    def neighbors(self) -> Iterator["ChunkCoord"]:
        for dq, dr in HexCoord.DIRECTIONS:  # type: ignore[attr-defined]
            yield ChunkCoord(self.q + dq, self.r + dr)


@dataclass
class MapChunk:
    """A cached section of the overworld grid."""

    coord: ChunkCoord
    chunk_size: int
    biomes: MutableMapping[Tuple[int, int], BiomeType] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

    def global_coord(self, local_q: int, local_r: int) -> HexCoord:
        q = self.coord.q * self.chunk_size + local_q
        r = self.coord.r * self.chunk_size + local_r
        return HexCoord(q, r)

    def biome_at_local(self, local_q: int, local_r: int) -> BiomeType | None:
        return self.biomes.get((local_q, local_r))

    def set_biome(self, local_q: int, local_r: int, biome: BiomeType) -> None:
        self.biomes[(local_q, local_r)] = biome

    def tiles(self) -> Iterator[Tuple[HexCoord, BiomeType]]:
        for (local_q, local_r), biome in self.biomes.items():
            yield self.global_coord(local_q, local_r), biome


class BiomeNoise:
    """Deterministic noise generator for biome classification."""

    def __init__(
        self,
        *,
        randomness: WorldRandomness | None = None,
        seed: int | None = None,
        channel: str = "biome",
        frequency: float = 0.1,
    ) -> None:
        if randomness is None:
            if seed is None:
                raise ValueError("Either randomness or seed must be provided")
            randomness = WorldRandomness(seed=seed)
        self._randomness = randomness
        self._noise: OpenSimplex = randomness.noise(channel)
        self._frequency = frequency

    def value(self, coord: HexCoord) -> float:
        sample = self._noise.noise2(coord.q * self._frequency, coord.r * self._frequency)
        return 0.5 + 0.5 * sample

    def biome(self, coord: HexCoord) -> BiomeType:
        sample = self.value(coord)
        if sample < 0.1:
            return BiomeType.WATER
        if sample < 0.35:
            return BiomeType.BARREN
        if sample < 0.6:
            return BiomeType.SCRUBLAND
        if sample < 0.85:
            return BiomeType.FOREST
        return BiomeType.HIGHLAND


class ChunkGenerator:
    """Generates map chunks using a biome noise source."""

    def __init__(self, chunk_size: int, biome_noise: BiomeNoise) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.chunk_size = chunk_size
        self.biome_noise = biome_noise

    def generate(self, coord: ChunkCoord) -> MapChunk:
        chunk = MapChunk(coord=coord, chunk_size=self.chunk_size)
        for local_q in range(self.chunk_size):
            for local_r in range(self.chunk_size):
                global_coord = chunk.global_coord(local_q, local_r)
                chunk.set_biome(local_q, local_r, self.biome_noise.biome(global_coord))
        return chunk


ChunkLoader = Callable[[ChunkCoord], MapChunk]


class ChunkStreamer:
    """Maintains an active window of map chunks around a focal point."""

    def __init__(self, chunk_size: int, loader: ChunkLoader) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.chunk_size = chunk_size
        self._loader = loader
        self._loaded: Dict[ChunkCoord, MapChunk] = {}

    @property
    def loaded_chunks(self) -> Mapping[ChunkCoord, MapChunk]:
        return self._loaded

    def get_chunk(self, coord: ChunkCoord) -> MapChunk | None:
        return self._loaded.get(coord)

    def update_window(self, center: HexCoord, radius: int) -> None:
        if radius < 0:
            raise ValueError("radius must be non-negative")
        center_chunk = center.to_chunk(self.chunk_size)
        desired: Dict[ChunkCoord, None] = {}
        for dq in range(-radius, radius + 1):
            for dr in range(-radius, radius + 1):
                coord = ChunkCoord(center_chunk.q + dq, center_chunk.r + dr)
                desired[coord] = None
                if coord not in self._loaded:
                    self._loaded[coord] = self._loader(coord)
        for coord in list(self._loaded.keys()):
            if coord not in desired:
                del self._loaded[coord]

    def tiles(self) -> Iterator[Tuple[HexCoord, BiomeType]]:
        for chunk in self._loaded.values():
            yield from chunk.tiles()


@dataclass
class SiteNetwork:
    """Generated site placements and their connectivity graph."""

    sites: Dict[str, Site]
    positions: Dict[str, HexCoord]
    connections: Dict[str, Dict[str, float]]

    def to_world_state(self) -> Dict[str, object]:
        """Return a mapping ready to merge into persistent world state."""

        position_payload = {
            identifier: {"q": coord.q, "r": coord.r}
            for identifier, coord in self.positions.items()
        }
        connection_payload = {
            identifier: dict(neighbours) for identifier, neighbours in self.connections.items()
        }
        return {
            "sites": self.sites,
            "site_graph": {
                "positions": position_payload,
                "connections": connection_payload,
            },
        }


_SITE_TYPE_WEIGHTS: Dict[SiteType, float] = {
    SiteType.CITY: 0.18,
    SiteType.FARM: 0.26,
    SiteType.POWER_PLANT: 0.12,
    SiteType.CAMP: 0.3,
    SiteType.MILITARY_RUINS: 0.14,
}

_SITE_ATTENTION_PROFILES: Dict[SiteType, tuple[float, float, float]] = {
    SiteType.CITY: (2.4, 40.0, 16.0),
    SiteType.FARM: (1.8, 28.0, 12.0),
    SiteType.POWER_PLANT: (2.0, 32.0, 14.0),
    SiteType.CAMP: (1.5, 22.0, 9.0),
    SiteType.MILITARY_RUINS: (2.2, 35.0, 13.0),
}

_SITE_POPULATION_RANGES: Dict[SiteType, tuple[int, int]] = {
    SiteType.CITY: (500, 2500),
    SiteType.FARM: (80, 400),
    SiteType.POWER_PLANT: (40, 200),
    SiteType.CAMP: (15, 120),
    SiteType.MILITARY_RUINS: (0, 150),
}


def generate_site_network(
    randomness: WorldRandomness,
    *,
    site_count: int = 8,
    radius: int = 6,
    center: HexCoord | None = None,
) -> SiteNetwork:
    """Procedurally place typed sites and build their connectivity graph."""

    if site_count <= 0:
        raise ValueError("site_count must be positive")
    if radius <= 0:
        raise ValueError("radius must be positive")
    center = center or HexCoord(0, 0)
    rng = randomness.generator("site-network")

    positions: Dict[str, HexCoord] = {}
    occupied: set[tuple[int, int]] = set()
    attempts = 0
    max_attempts = max(32, site_count * 20)
    while len(positions) < site_count and attempts < max_attempts:
        dq = int(rng.integers(-radius, radius + 1))
        dr = int(rng.integers(-radius, radius + 1))
        coord = center.translate(dq, dr)
        if coord.distance_to(center) > radius:
            attempts += 1
            continue
        key = (coord.q, coord.r)
        if key in occupied:
            attempts += 1
            continue
        identifier = f"site-{len(positions) + 1:02d}"
        positions[identifier] = coord
        occupied.add(key)
    if len(positions) < site_count:
        raise RuntimeError("failed to place the requested number of sites within radius")

    weights_total = sum(_SITE_TYPE_WEIGHTS.values())
    type_choices = list(_SITE_TYPE_WEIGHTS.keys())
    probabilities = [weight / weights_total for weight in _SITE_TYPE_WEIGHTS.values()]

    sites: Dict[str, Site] = {}
    for identifier in positions:
        choice_index = int(rng.choice(len(type_choices), p=probabilities))
        site_type: SiteType = type_choices[choice_index]
        peak, mu, sigma = _SITE_ATTENTION_PROFILES[site_type]
        curve = AttentionCurve(
            peak=max(0.1, peak + float(rng.uniform(-0.2, 0.2))),
            mu=max(0.0, mu + float(rng.uniform(-5.0, 5.0))),
            sigma=max(1.0, sigma + float(rng.uniform(-2.0, 2.0))),
        )
        pop_low, pop_high = _SITE_POPULATION_RANGES[site_type]
        population = int(rng.integers(pop_low, pop_high + 1))
        exploration = float(rng.uniform(0.0, 5.0))
        scavenged = float(rng.uniform(0.0, 3.0))
        sites[identifier] = Site(
            identifier=identifier,
            site_type=site_type,
            exploration_percent=exploration,
            scavenged_percent=scavenged,
            population=population,
            attention_curve=curve,
        )

    connections: Dict[str, Dict[str, float]] = {identifier: {} for identifier in positions}
    for identifier, origin in positions.items():
        neighbours = [
            (other_id, origin.distance_to(target))
            for other_id, target in positions.items()
            if other_id != identifier
        ]
        neighbours.sort(key=lambda item: item[1])
        max_edges = 2 if len(neighbours) > 2 else len(neighbours)
        for neighbour_id, distance in neighbours[:max_edges]:
            cost = float(max(1, distance))
            connections[identifier][neighbour_id] = cost
            connections.setdefault(neighbour_id, {})[identifier] = cost

    for identifier, neighbours in connections.items():
        site = sites[identifier]
        for neighbour_id, cost in neighbours.items():
            site.connect(neighbour_id, cost=cost)

    ordered_connections = {
        identifier: dict(sorted(neighbours.items())) for identifier, neighbours in connections.items()
    }

    return SiteNetwork(sites=sites, positions=positions, connections=ordered_connections)


__all__ = [
    "BiomeType",
    "HexCoord",
    "ChunkCoord",
    "MapChunk",
    "BiomeNoise",
    "ChunkGenerator",
    "ChunkStreamer",
    "SiteNetwork",
    "generate_site_network",
]
