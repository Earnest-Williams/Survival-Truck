"""Persistence helpers for world map chunks and site state."""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from .sites import Site
from .map import BiomeType, ChunkCoord, MapChunk


def serialize_chunk(chunk: MapChunk) -> Dict[str, object]:
    """Convert a :class:`MapChunk` into a JSON friendly payload."""

    return {
        "chunk": {"q": chunk.coord.q, "r": chunk.coord.r},
        "chunk_size": chunk.chunk_size,
        "biomes": [
            {"local_q": q, "local_r": r, "biome": biome.value}
            for (q, r), biome in chunk.biomes.items()
        ],
    }


def deserialize_chunk(payload: Dict[str, object]) -> MapChunk:
    """Reconstruct a :class:`MapChunk` from serialized data."""

    chunk_data = payload.get("chunk", {})
    if not isinstance(chunk_data, dict):
        raise TypeError("chunk metadata must be a mapping")
    coord = ChunkCoord(int(chunk_data.get("q", 0)), int(chunk_data.get("r", 0)))
    chunk_size = int(payload.get("chunk_size", 0))
    chunk = MapChunk(coord=coord, chunk_size=chunk_size)
    biomes_payload = payload.get("biomes", [])
    if not isinstance(biomes_payload, Iterable):
        raise TypeError("biomes payload must be iterable")
    for tile in biomes_payload:
        if not isinstance(tile, dict):
            continue
        biome_raw = tile.get("biome")
        if biome_raw is None:
            continue
        biome_value = BiomeType(str(biome_raw))
        local_q = int(tile.get("local_q", 0))
        local_r = int(tile.get("local_r", 0))
        chunk.set_biome(local_q, local_r, biome_value)
    return chunk


def serialize_chunks(chunks: Iterable[MapChunk]) -> List[Dict[str, object]]:
    return [serialize_chunk(chunk) for chunk in chunks]


def deserialize_chunks(payload: Sequence[Dict[str, object]]) -> List[MapChunk]:
    return [deserialize_chunk(item) for item in payload]


def serialize_site(site: Site) -> Dict[str, object]:
    return site.to_dict()


def deserialize_site(payload: Dict[str, object]) -> Site:
    return Site.from_dict(payload)


def serialize_sites(sites: Iterable[Site]) -> List[Dict[str, object]]:
    return [site.to_dict() for site in sites]


def deserialize_sites(payload: Sequence[Dict[str, object]]) -> List[Site]:
    return [Site.from_dict(item) for item in payload]
