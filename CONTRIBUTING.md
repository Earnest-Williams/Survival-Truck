# Contributing

Thanks for helping build Survival Truck! This guide documents how to set up a development environment and run checks using Poetry.

## Environment setup

1. Install [Poetry 2.1+](https://python-poetry.org/docs/#installation).
2. Create a virtual environment and install dependencies:

   ```bash
   poetry install
   ```

Poetry will create `.venv` inside the project directory unless configured otherwise. The `poetry.lock` file should be committed whenever dependencies change so everyone shares the same set of packages.

## Running the game locally

Launch the Textual interface through Poetry to ensure the environment matches the lockfile:

```bash
poetry run survival-truck
```

## Tests and quality checks

Run the automated test suite with:

```bash
poetry run pytest
```

Add new tests when contributing features, especially for gameplay rules and persistence logic. If you add new dependencies, update `pyproject.toml` and regenerate the lockfile via `poetry lock`.
