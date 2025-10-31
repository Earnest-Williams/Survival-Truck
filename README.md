# Survival Truck

*A turn-based post-collapse survival and logistics simulation rendered as a terminal/TUI game.*

## Overview

You drive a modular expedition truck across a persistent hex-grid world. Each day you travel, scavenge, trade, or build while NPC factions operate under the same rules. The interface is ASCII-first using a modern terminal UI powered by [Textual](https://textual.textualize.io/).

- **Target runtime:** Python 3.12+
- **Supported platforms:** Linux, macOS, and Windows with a UTF-8 compatible terminal

## Installation

The repository is packaged with [Poetry](https://python-poetry.org/) to keep runtime and tooling dependencies in sync. The steps below assume you are starting with a clean checkout of this repository.

### Recommended: Poetry workflow

1. Install Poetry (version 2.1 or newer). The maintainers recommend using [`pipx`](https://pipx.pypa.io/) so the tool stays isolated:

   ```bash
   pipx install poetry
   ```

2. Clone the repository and create the virtual environment with all runtime and developer dependencies:

   ```bash
   git clone https://github.com/survival-truck/Survival-Truck.git
   cd Survival-Truck
   poetry install --with dev
   ```

3. Run the game from the managed environment:

   ```bash
   poetry run survival-truck
   ```

4. Execute the automated test suite (optional but recommended for contributors):

   ```bash
   poetry run pytest
   ```

Poetry maintains the `poetry.lock` file checked into the repository so repeat installs are reproducible across machines.

### Alternative: Editable install with pip

If you prefer to work without Poetry you can still rely on the packaging metadata exported in `pyproject.toml`:

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -U pip
pip install -e .

# Launch the Textual interface
survival-truck

# Run tests
python -m pytest
```

This flow installs the same console script entry point declared for Poetry users while letting you control your own virtual environment.

### Dependency reference

The authoritative dependency list lives in [`pyproject.toml`](pyproject.toml):

```toml
[tool.poetry.dependencies]
python = "^3.12"
textual = "^0.60.1"
rich = "^13.8.0"
networkx = "^3.4.2"
sqlmodel = "^0.0.22"
sqlalchemy = "^2.0.32"
numpy = "^2.1.1"
opensimplex = "^0.4.5"
pydantic = "^2.9.2"
esper = "^2.5"
msgpack = "^1.0.8"
zstandard = "^0.23.0"
platformdirs = "^4.3.6"
polars = "^1.9.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3.3"
pytest-cov = "^5.0.0"
```

## World and Game Structure

* **Hex world:** Procedurally generated, persistent.
* **Sites:** Cities, farms, power plants, survivor camps, military ruins.
* **Attention curve:** Yield versus time-on-site with rising risk.
* **NPC factions:** Trade, alliances, wars, migration.
* **Turns:** One day per turn; seasons and weather matter.
* **Truck:** Modular cabins, trailers, sensors, turrets; weight, power, storage, fuel.
* **Crew:** Skills, traits, relationships; recruitment and loss.
* **Resources:** Fuel, food, water, parts, ammunition, trade goods, salvage.

---

## Python Tech Stack

### Core libraries by function

| Function                      | Library/libraries             | Why it’s used                                                   |
| ----------------------------- | ----------------------------- | ---------------------------------------------------------------- |
| **TUI rendering**             | `textual`, `rich`             | Compose panes, widgets, and stylised terminal output.             |
| **Graphs & pathfinding**      | `networkx`                    | Diplomacy graphs, logistics networks, and route calculations.     |
| **Persistence / ORM**         | `sqlmodel`, `sqlalchemy`      | Typed models on SQLite backed by SQLAlchemy’s engine. |
| **Data validation**           | `pydantic`                    | Runtime-validated configs, saves, and schema definitions. |
| **ECS**                       | `esper`                       | Lightweight entity-component-system loop. |
| **State machines**            | `polars`                      | Data-driven tables driving AI state flow. |
| **RNG & numerics**            | `numpy`                       | Deterministic seeding and vectorised random draws. |
| **Noise fields**              | `opensimplex`                 | Procedural terrain and resource layers. |
| **Serialization & compression** | `msgpack`, `zstandard`      | Compact, compressed world snapshots and diffs. |
| **Config & save paths**       | `platformdirs`                | OS-appropriate locations for config, cache, and save data. |
| **Testing**                   | `pytest`, `pytest-cov`        | Core unit tests and coverage reporting. |
| **Packaging**                 | `poetry`                      | Dependency management and application entry points. |

> Minimalism rule: prefer stdlib where feasible; add third-party only where it saves real time or improves clarity.

---

## Systems Interconnection

**World Generation**

* Seed → `numpy.random.Generator`.
* Terrain/resource layers → `opensimplex`.
* Regions and roads → `networkx` graphs (sites as nodes, roads as edges).
* Output validated by `pydantic` and written via `sqlmodel`/`sqlalchemy` to SQLite.

**Simulation Core (per day)**

* Entities in `esper` (truck, crew, sites, caravans, factions).
* Systems run in order: movement → site exploitation → maintenance → diplomacy → events.
* Scheduled effects in `heapq` (repairs complete on day N, storms arrive day M).
* AI state flow uses Polars-driven tables and consults `networkx` (routes/relations).
* Pathfinding via `networkx` weighted shortest paths over the hex graph.

**Persistence**

* Daily diffs as `msgpack` blobs compressed with `zstandard`; seasonal full snapshots.
* World index and metadata in SQLite via `sqlmodel`/`sqlalchemy`.
* Configs and schema with `pydantic`.

**Interface**

* `textual` app with panes: Map, Log, Status, Truck, Diplomacy.
* Hotkeys handled by `textual` bindings.
* Optional developer charts can be generated if you install `matplotlib` yourself; it is not bundled with the main runtime dependencies.

---

## Data Model (high level)

* `WorldConfig` (pydantic): seed, map size, biome weights, difficulty.
* `Site`: id, hex, type, explored_pct, scavenged_pct, faction_id, hostility.
* `Faction`: id, ideology, posture, treasury, graph node.
* `Truck`: power, weight, storage, range, modules[], visibility.
* `Crew`: name, skills{}, traits[], fatigue, morale, relations{}.
* `ResourceState`: fuel, food, water, parts, ammo, goods, salvage.
* `Event`: time, type, payload.
* `SaveSlot`: metadata, last_turn, season, checksum.

---

## Gameplay Algorithms

**Attention curve per site**

* Yield/day = `peak * exp(-((t - mu)^2) / (2*sigma^2))` with site-specific `mu`, `sigma`, `peak`.
* Risk/day increases with t via logistic: `risk = L / (1 + e^{-k (t - t0)})`.
* Parameters come from site archetype + randomness + world modifiers.

**Travel cost**

* Base fuel per hex * terrain multiplier * (weight / power factor).
* Weather reduces effective traction; breakdown risk ~ load and terrain roughness.

**Faction decisions**

* State machine: `Patrol ↔ Trade ↔ Raid ↔ Consolidate ↔ Ally`.
* Utilities draw from needs (fuel/food/tech), relations, distance, recent events.

---

## Project Structure

```
Survival-Truck/
  README.md
  pyproject.toml
  poetry.lock
  CONTRIBUTING.md
  notes.md
  game/
    __init__.py
    __main__.py             # CLI entry that launches the Textual UI
    crew/
      __init__.py           # Crew models, needs, and skill checks
    engine/
      __init__.py
      resource_pipeline.py  # Resource consumption and production phases
      turn_engine.py        # Daily turn sequencing and turn context
      world.py              # ECS world wrapper and system registration
    events/
      __init__.py
      event_queue.py        # Priority queue of scheduled game events
    factions/
      __init__.py
      ai.py                 # NPC faction state machines and behaviours
      trade.py              # Trade evaluation and exchange helpers
    time/
      __init__.py
      season_tracker.py     # Calendar progression and seasonal modifiers
      weather.py            # Weighted daily weather generation
    truck/
      __init__.py
      inventory.py          # Cargo accounting and spoilage tracking
      models.py             # Truck configuration and maintenance logic
    ui/
      __init__.py
      app.py                # Textual application wiring and layout
      channels.py           # Message channels feeding logs and notifications
      control_panel.py      # Turn planning helpers and control panel widget
      dashboard.py          # Status panels and turn log renderers
      diplomacy.py          # Diplomacy view composition
      hex_map.py            # Hex-map widget and navigation helpers
      truck_layout.py       # Truck layout visualisation
    world/
      __init__.py
      config.py             # Pydantic world generation and storage configs
      graph.py              # Graph utilities for travel and diplomacy
      map/
        __init__.py         # Hex grid types, biome noise, and chunk caching
      persistence.py        # Save-slot storage and msgpack serialisation
      rng.py                # Seeded RNG and noise helper factory
      save_models.py        # Serializable models for world snapshots
      settlements.py        # Settlement simulation tied to sites
      sites.py              # Site state, attention curves, and interactions
  tests/
    test_crew_lifecycle.py
    test_event_queue.py
    test_faction_ai.py
    test_package_metadata.py
    test_ui_diplomacy.py
    test_weather_system.py
    test_world_graph.py
    test_world_persistence_models.py
```

---

## Minimal Bootstraps

### Textual app skeleton

```python
# survival_truck/app.py
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static

class MapView(Static): pass
class LogView(Static): pass
class StatusView(Static): pass

class SurvivalTruckApp(App):
    CSS = """
    Screen { layout: grid; grid-size: 2 2; grid-gutter: 1; }
    MapView { grid-column: 1 / 2; grid-row: 1; row-span: 2; }
    LogView { grid-column: 2; grid-row: 1; height: 1fr; }
    StatusView { grid-column: 2; grid-row: 2; height: 1fr; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("space", "next_turn", "Next Day")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield MapView("…map…")
        yield LogView("Day 1: You arrive at the outskirts of a ruined town.")
        yield StatusView("Fuel 100 | Food 40 | Water 60 | Parts 12")
        yield Footer()

    def action_next_turn(self):
        # TODO: advance ECS and rerender panels
        pass

if __name__ == "__main__":
    SurvivalTruckApp().run()
```

### Deterministic RNG and noise

```python
# survival_truck/rng.py
import numpy as np
from opensimplex import OpenSimplex

def make_rng(seed: int | str):
    if isinstance(seed, str):
        seed = abs(hash(seed)) % (2**63)
    return np.random.Generator(np.random.PCG64(seed))

def make_noise(seed: int | str):
    if isinstance(seed, str):
        seed = abs(hash(seed)) % (2**31)
    return OpenSimplex(seed)
```

### ECS world and a turn tick

```python
# survival_truck/ecs/world.py
import esper

class GameWorld:
    def __init__(self):
        self.ecs = esper.World()
        self.turn = 1

    def tick(self):
        # systems run in deterministic order
        # self.ecs.process(movement)
        # self.ecs.process(exploitation)
        # self.ecs.process(maintenance)
        # self.ecs.process(diplomacy)
        # self.ecs.process(events)
        self.turn += 1
```

---

## Balancing and Debugging

* Plot attention curves and yields with your own tooling (for example, install `matplotlib` manually for ad-hoc analysis).
* Keep all randomness behind `rng.make_rng(seed)` for reproducibility.
* Store daily diffs and seasonal snapshots; allow rollback for profiling.

---

## Design and Technical Pillars

**Design:** shared rules for player and NPCs; modular truck as mechanical core; persistent, deterministic world; ASCII/TUI clarity.

**Technical:** Textual/Rich TUI; Esper ECS; NumPy RNG; OpenSimplex terrain; NetworkX diplomacy/routes; SQLite + msgpack saves; Pydantic validation.

---

## Roadmap (first milestones)

1. Seeded world gen: terrain, sites, factions.
2. ECS core: movement, exploitation, maintenance.
3. Textual map and panels with keyboard controls.
4. Saves: SQLite indices + msgpack snapshots.
5. Faction AI via Polars state tables and NetworkX.
6. Balancing pass on attention curves and travel costs.
7. Performance pass; optional worker offload.

---
