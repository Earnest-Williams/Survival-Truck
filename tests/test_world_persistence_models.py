from __future__ import annotations

from pathlib import Path

import pytest

from game.world.config import DifficultyLevel, WorldConfig, WorldMapSettings, WorldRandomnessSettings
from game.world.map import BiomeType, ChunkCoord, MapChunk
from game.world.persistence import (
    create_world_engine,
    init_world_storage,
    iter_daily_diffs,
    load_daily_diff,
    load_world_config,
    store_daily_diff,
    store_world_config,
)
from game.world.save_models import WorldSnapshot
from game.world.sites import AttentionCurve, Site


def _make_chunk() -> MapChunk:
    chunk = MapChunk(coord=ChunkCoord(0, 0), chunk_size=2)
    chunk.set_biome(0, 0, BiomeType.BARREN)
    chunk.set_biome(1, 1, BiomeType.FOREST)
    return chunk


def _make_site(identifier: str = "alpha") -> Site:
    return Site(
        identifier=identifier,
        population=12,
        exploration_percent=10.0,
        scavenged_percent=5.0,
        attention_curve=AttentionCurve(base=1.0, growth=0.5, decay=0.1),
    )


def test_world_config_validation() -> None:
    config = WorldConfig(
        name="Campaign",  # simple metadata
        randomness=WorldRandomnessSettings(seed=99),
        map=WorldMapSettings(chunk_size=6, view_radius=3, biome_frequency=0.2),
        metadata={"season": "spring"},
    )
    assert config.seed == 99
    assert config.difficulty is DifficultyLevel.STANDARD
    weights = config.biome_weights.normalised
    assert pytest.approx(sum(weights.values()), rel=1e-9) == 1.0
    assert config.metadata["season"] == "spring"


def test_world_snapshot_round_trip() -> None:
    chunk = _make_chunk()
    site = _make_site()
    world_state = {
        "notes": ["Arrived at camp"],
        "progress": {"scavenge": 2},
        "randomness": object(),
        "sites": {site.identifier: site},
    }
    snapshot = WorldSnapshot.from_components(day=5, chunks=[chunk], world_state=world_state)
    assert snapshot.day == 5
    assert "randomness" not in snapshot.world_state
    assert snapshot.world_state["notes"] == ["Arrived at camp"]

    restored_chunks = snapshot.to_chunks()
    assert restored_chunks[0].biome_at_local(1, 1) == BiomeType.FOREST

    restored_sites = snapshot.to_site_map()
    assert restored_sites[site.identifier].population == site.population

    restored_state = snapshot.to_world_state()
    assert restored_state["notes"] == ["Arrived at camp"]
    assert site.identifier in restored_state["sites"]
    assert isinstance(restored_state["sites"][site.identifier], Site)


def test_persistence_round_trip(tmp_path: Path) -> None:
    engine = create_world_engine(tmp_path / "world.db")
    init_world_storage(engine)

    config = WorldConfig(
        name="Campaign",
        randomness=WorldRandomnessSettings(seed=123),
        map=WorldMapSettings(chunk_size=4, view_radius=2),
    )
    store_world_config(engine, "slot-a", config)
    loaded_config = load_world_config(engine, "slot-a")
    assert loaded_config == config

    chunk = _make_chunk()
    site = _make_site("beta")
    snapshot = WorldSnapshot.from_components(
        day=3,
        chunks=[chunk],
        sites={site.identifier: site},
        world_state={"notes": ["Camp established"]},
    )
    metadata = store_daily_diff(engine, "slot-a", snapshot)
    assert metadata.day == 3
    assert metadata.site_count == 1

    loaded = load_daily_diff(engine, "slot-a", 3)
    assert loaded is not None
    loaded_metadata, loaded_snapshot = loaded
    assert loaded_metadata.day == 3
    assert loaded_metadata.site_count == 1

    restored_state = loaded_snapshot.to_world_state()
    assert restored_state["notes"] == ["Camp established"]
    assert "beta" in restored_state["sites"]

    records = list(iter_daily_diffs(engine, "slot-a"))
    assert len(records) == 1
    iter_metadata, iter_snapshot = records[0]
    assert iter_metadata == loaded_metadata
    assert iter_snapshot.to_site_map()["beta"].identifier == "beta"
