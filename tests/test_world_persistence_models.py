from __future__ import annotations

from pathlib import Path

import pytest

from game.crew import SkillCheckResult, SkillType
from game.world.config import DifficultyLevel, WorldConfig, WorldMapSettings, WorldRandomnessSettings
from game.world.map import BiomeType, ChunkCoord, MapChunk, generate_site_network
from game.world.persistence import (
    create_world_engine,
    init_world_storage,
    iter_daily_diffs,
    load_daily_diff,
    load_world_config,
    store_daily_diff,
    store_world_config,
)
from game.world.rng import WorldRandomness
from game.world.save_models import WorldSnapshot
from game.world.sites import AttentionCurve, Site, SiteType


def _make_chunk() -> MapChunk:
    chunk = MapChunk(coord=ChunkCoord(0, 0), chunk_size=2)
    chunk.set_biome(0, 0, BiomeType.BARREN)
    chunk.set_biome(1, 1, BiomeType.FOREST)
    return chunk


def _make_site(
    identifier: str = "alpha",
    *,
    site_type: SiteType = SiteType.CAMP,
    connections: dict[str, float] | None = None,
) -> Site:
    return Site(
        identifier=identifier,
        site_type=site_type,
        population=12,
        exploration_percent=10.0,
        scavenged_percent=5.0,
        attention_curve=AttentionCurve(peak=1.6, mu=5.0, sigma=2.0),
        connections=connections or {},
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
    site = _make_site(connections={"delta": 2.0})
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
    restored_site = restored_sites[site.identifier]
    assert restored_site.population == site.population
    assert restored_site.site_type is SiteType.CAMP
    assert restored_site.connections == {"delta": 2.0}
    assert restored_site.attention_curve == site.attention_curve

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
    site_beta = _make_site("beta", site_type=SiteType.FARM, connections={"gamma": 3.0})
    site_gamma = _make_site("gamma", site_type=SiteType.CITY, connections={"beta": 3.0})
    snapshot = WorldSnapshot.from_components(
        day=3,
        chunks=[chunk],
        sites={site_beta.identifier: site_beta, site_gamma.identifier: site_gamma},
        world_state={
            "notes": ["Camp established"],
            "site_graph": {
                "connections": {
                    site_beta.identifier: site_beta.connections,
                    site_gamma.identifier: site_gamma.connections,
                }
            },
        },
    )
    metadata = store_daily_diff(engine, "slot-a", snapshot)
    assert metadata.day == 3
    assert metadata.site_count == 2

    loaded = load_daily_diff(engine, "slot-a", 3)
    assert loaded is not None
    loaded_metadata, loaded_snapshot = loaded
    assert loaded_metadata.day == 3
    assert loaded_metadata.site_count == 2

    restored_state = loaded_snapshot.to_world_state()
    assert restored_state["notes"] == ["Camp established"]
    restored_sites = restored_state["sites"]
    assert "beta" in restored_sites
    assert "gamma" in restored_sites
    assert restored_sites["beta"].site_type is SiteType.FARM
    assert "gamma" in restored_sites["beta"].connections
    assert restored_sites["gamma"].site_type is SiteType.CITY
    assert "beta" in restored_sites["gamma"].connections

    records = list(iter_daily_diffs(engine, "slot-a"))
    assert len(records) == 1
    iter_metadata, iter_snapshot = records[0]
    assert iter_metadata == loaded_metadata
    iter_sites = iter_snapshot.to_site_map()
    assert iter_sites["beta"].identifier == "beta"
    assert iter_sites["gamma"].connections == {"beta": 3.0}


def test_site_generation_network_round_trip() -> None:
    randomness = WorldRandomness(seed=77)
    network = generate_site_network(randomness, site_count=4, radius=4)
    assert len(network.sites) == 4
    world_state = network.to_world_state()

    snapshot = WorldSnapshot.from_components(
        day=8,
        chunks=[_make_chunk()],
        sites=network.sites,
        world_state=world_state,
    )

    restored_sites = snapshot.to_site_map()
    assert len(restored_sites) == 4
    for site in restored_sites.values():
        assert isinstance(site.site_type, SiteType)
        for neighbour, cost in site.connections.items():
            assert neighbour in restored_sites
            assert cost >= 1.0

    restored_state = snapshot.to_world_state()
    graph = restored_state.get("site_graph")
    assert graph is not None
    assert set(graph["connections"]) == set(network.connections)


def test_site_scavenge_uses_gaussian_profile() -> None:
    site = _make_site()
    site.scavenged_percent = site.attention_curve.mu
    result = SkillCheckResult(
        skill=SkillType.SCAVENGING,
        difficulty=10.0,
        roll=10.0,
        success=True,
        margin=0.0,
        participants=(),
    )
    expected = max(0.5, 4.0 + result.margin) * max(0.05, site.attention_curve.value_at(site.scavenged_percent))
    progress = site.resolve_scavenge_attempt(result)
    assert pytest.approx(progress, rel=1e-6) == expected


def test_negotiation_adjusts_gaussian_parameters() -> None:
    site = _make_site()
    before = site.attention_curve
    result = SkillCheckResult(
        skill=SkillType.NEGOTIATION,
        difficulty=12.0,
        roll=16.0,
        success=True,
        margin=4.0,
        participants=("envoy",),
    )
    site.resolve_negotiation_attempt(result, faction="allies")
    after = site.attention_curve
    assert after.peak > before.peak
    assert 0.0 <= after.mu <= 100.0
    assert after.sigma <= before.sigma
