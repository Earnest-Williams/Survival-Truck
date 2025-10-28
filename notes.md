# Structural Improvement Notes

- **Adopt a Textual application shell for the TUI.** Build on the existing Rich view classes by wrapping them in a `textual` `App` with panes for map, log, status, and truck management so that the interface aligns with the README's Textual-first design and gains keyboard bindings.
- **Centralize randomness and terrain generation with NumPy + OpenSimplex.** Replace ad hoc `random.Random` usage in the map generator and resource systems with a deterministic `numpy.random.Generator` and `opensimplex` noise field seeded from campaign settings.
- **Introduce an Esper-powered ECS world core.** Layer the current `TurnEngine` orchestration over an `esper.World` so that entities (truck, crew, factions, sites) and their systems follow the ECS architecture described in the README.
- **Move the event queue to a heap-based scheduler.** Swap the deque-backed `EventQueue` for a `heapq` priority queue to ensure deterministic, efficient scheduling that matches the roadmap guidance.
- **Model world configuration and saves with Pydantic + SQLModel.** Define validated configuration/snapshot schemas with `pydantic` and persist them in SQLite through `sqlmodel`, enabling the daily diff and snapshot strategy outlined in the README.
- **Add pathfinding and diplomacy graphs with NetworkX.** Represent site connectivity, trade routes, and faction relations using NetworkX graphs to support A* movement and strategic AI.
- **Establish Poetry/uv-based project packaging.** Add a project configuration (`pyproject.toml`) that enumerates the recommended runtime and development dependencies, improving onboarding and reproducibility.

