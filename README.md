# Survival Truck

*A turn-based post-collapse survival and logistics simulation rendered as a terminal/TUI game.*

---

## 1) Overview

You drive a modular expedition truck across a persistent hex-grid world. Each day you travel, scavenge, trade, or build. NPC factions operate under the same rules. The interface is ASCII-first using a modern terminal UI.

Target runtime: **Python 3.12+**
OS: Linux, macOS, Windows (UTF-8 terminal recommended)

---

## Installation

This project is managed with [Poetry](https://python-poetry.org/) for reproducible environments and lockfiles.

1. Install Poetry (version 2.1+ recommended).
2. Create the virtual environment and install dependencies:

   ```bash
   poetry install
   ```

3. Launch the Textual interface from the Poetry environment:

   ```bash
   poetry run survival-truck
   ```

4. Run the automated test suite:

   ```bash
   poetry run pytest
   ```

The generated `poetry.lock` file pins transitive dependencies to ensure consistent builds across machines.

---

## 2) World and Game Structure

* **Hex world:** Procedurally generated, persistent.
* **Sites:** Cities, farms, power plants, survivor camps, military ruins.
* **Attention curve:** Yield versus time-on-site with rising risk.
* **NPC factions:** Trade, alliances, wars, migration.
* **Turns:** One day per turn; seasons and weather matter.
* **Truck:** Modular cabins, trailers, sensors, turrets; weight, power, storage, fuel.
* **Crew:** Skills, traits, relationships; recruitment and loss.
* **Resources:** Fuel, food, water, parts, ammunition, trade goods, salvage.

---

## 3) Python Tech Stack

### 3.1 Core libraries by function

| Function                      | Library                                                            | Why                                                               |
| ----------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------- |
| **TUI rendering**             | `textual` (+ `rich`)                                               | Fast, composable terminal UI, panels, tables, keyboard input.     |
| **Hex math**                  | `hexalattice` *(for layout utilities)* or custom axial/cube module | Axial/cube coords, rings, ranges. Minimal dependencies preferred. |
| **Pathfinding**               | `pathfinding` or `networkx` A*                                     | Weighted A* on grids; `networkx` doubles for road graphs.         |
| **Noise fields**              | `opensimplex` or `noise`                                           | Terrain, resource richness, weather.                              |
| **RNG / distributions**       | `numpy` random `Generator` (PCG64 or SFC64)                        | Deterministic seeding, vectorised draws.                          |
| **ECS**                       | `esper`                                                            | Lightweight, pure-Python ECS.                                     |
| **Event queue**               | stdlib `heapq`                                                     | Deterministic priority queue for scheduled events.                |
| **FSM / statecharts**         | `transitions`                                                      | Declarative state machines for AI and UI flows.                   |
| **Graphs (diplomacy/trade)**  | `networkx`                                                         | Relations, routes, coalition logic.                               |
| **Data validation**           | `pydantic` v2                                                      | Runtime-validated configs, saves, module specs.                   |
| **Persistence (DB)**          | `sqlite3` + `sqlmodel` or `sqlite-utils`                           | Simple, durable world storage; easy queries.                      |
| **Serialization (snapshots)** | `msgpack` or `orjson` + `zstandard`                                | Compact saves and seasonal snapshots.                             |
| **Job offloading**            | `multiprocessing` / `concurrent.futures`                           | Background world ticks and path searches.                         |
| **Dev charts (optional)**     | `matplotlib`                                                       | Balancing plots: attention curves, fuel series.                   |
| **Config & paths**            | `platformdirs`, `tomli`                                            | OS-appropriate save/config paths; TOML configs.                   |
| **Packaging**                 | `poetry` or `uv`                                                   | Reproducible env, lockfile, scripts.                              |

> Minimalism rule: prefer stdlib where feasible; add third-party only where it saves real time or improves clarity.

---

## 4) Systems Interconnection

**World Generation**

* Seed → `numpy.random.Generator`.
* Terrain/resource layers → `opensimplex`.
* Regions and roads → `networkx` graphs (sites as nodes, roads as edges).
* Output validated by `pydantic` and written to SQLite.

**Simulation Core (per day)**

* Entities in `esper` (truck, crew, sites, caravans, factions).
* Systems run in order: movement → site exploitation → maintenance → diplomacy → events.
* Scheduled effects in `heapq` (repairs complete on day N, storms arrive day M).
* AI state machines with `transitions` consult `networkx` (routes/relations).
* Pathfinding via `pathfinding` A* over hex costs.

**Persistence**

* Daily diffs as `msgpack` blobs; seasonal full snapshots.
* World index and metadata in SQLite via `sqlmodel`.
* Configs and schema with `pydantic`.

**Interface**

* `textual` app with panes: Map, Log, Status, Truck, Diplomacy.
* Hotkeys handled by `textual` bindings.
* Optional developer charts via `matplotlib` in a separate debug mode.

---

## 5) Data Model (high level)

* `WorldConfig` (pydantic): seed, map size, biome weights, difficulty.
* `Site`: id, hex, type, explored_pct, scavenged_pct, faction_id, hostility.
* `Faction`: id, ideology, posture, treasury, graph node.
* `Truck`: power, weight, storage, range, modules[], visibility.
* `Crew`: name, skills{}, traits[], fatigue, morale, relations{}.
* `ResourceState`: fuel, food, water, parts, ammo, goods, salvage.
* `Event`: time, type, payload.
* `SaveSlot`: metadata, last_turn, season, checksum.

---

## 6) Gameplay Algorithms

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

## 7) Project Structure

```
survival_truck/
  pyproject.toml
  survival_truck/
    __init__.py
    app.py                 # Textual entry point
    main.py                # CLI bootstrap
    config.py              # pydantic models, defaults
    rng.py                 # seeded numpy Generator helpers
    hexgrid/
      __init__.py
      coords.py            # axial/cube, rings, ranges
      path.py              # adapters to pathfinding
    world/
      gen.py               # noise-based terrain, sites
      sites.py             # site types, attention params
      weather.py
      factions.py
      graphs.py            # networkx builders
    ecs/
      world.py             # esper World setup
      components.py
      systems/
        movement.py
        exploitation.py
        maintenance.py
        diplomacy.py
        events.py
    ai/
      machines.py          # transitions definitions
    data/
      schema.py            # pydantic models (Site, Truck, Crew, etc.)
      persist.py           # sqlite/sqlmodel + msgpack IO
    ui/
      views.py             # Textual screens/panels
      map_widget.py        # ASCII map widget
      input.py
      theme.py
    devtools/
      balance.py           # plot attention curves (matplotlib)
      prof.py
  tests/
    test_hex.py
    test_attention.py
    test_persist.py
```

---

## 8) Installation and Running

Using **Poetry**:

```bash
# Python 3.12+ recommended
pipx install poetry

git clone https://github.com/<you>/Survival_Truck_Py.git
cd Survival_Truck_Py
poetry install --with dev
poetry run survival-truck
```

## 9) Minimal Bootstraps

### 9.1 Textual app skeleton

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
    MapView { grid-column: 1 / 2; grid-row: 1 / 3; }
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

### 9.2 Deterministic RNG and noise

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

### 9.3 ECS world and a turn tick

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

## 10) Balancing and Debugging

* Plot attention curves and yields with `devtools/balance.py` using `matplotlib`.
* Keep all randomness behind `rng.make_rng(seed)` for reproducibility.
* Store daily diffs and seasonal snapshots; allow rollback for profiling.

---

## 11) Design and Technical Pillars

**Design:** shared rules for player and NPCs; modular truck as mechanical core; persistent, deterministic world; ASCII/TUI clarity.

**Technical:** Textual/Rich TUI; Esper ECS; NumPy RNG; OpenSimplex terrain; NetworkX diplomacy/routes; SQLite + msgpack saves; Pydantic validation.

---

## 12) Roadmap (first milestones)

1. Seeded world gen: terrain, sites, factions.
2. ECS core: movement, exploitation, maintenance.
3. Textual map and panels with keyboard controls.
4. Saves: SQLite indices + msgpack snapshots.
5. Faction AI via `transitions` and NetworkX.
6. Balancing pass on attention curves and travel costs.
7. Performance pass; optional worker offload.

---
