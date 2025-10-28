"""Hex-based world map utilities with chunk streaming and biome noise."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, ClassVar, Dict, Iterator, Mapping, MutableMapping, Tuple
import random


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

    def __init__(self, seed: int) -> None:
        self.seed = seed

    def value(self, coord: HexCoord) -> float:
        local_seed = hash((self.seed, coord.q, coord.r))
        rng = random.Random(local_seed)
        return rng.random()

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


__all__ = [
    "BiomeType",
    "HexCoord",
    "ChunkCoord",
    "MapChunk",
    "BiomeNoise",
    "ChunkGenerator",
    "ChunkStreamer",
]
