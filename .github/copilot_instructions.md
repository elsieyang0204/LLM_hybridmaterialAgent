# Copilot Instructions Alias

This file mirrors the project guidance in `.github/copilot-instructions.md` for compatibility with underscore naming.

## Dynamic Constraints Rollback Switch
- `DYNAMIC_CONSTRAINTS=true` (default): enable KG-driven dynamic constraint inference.
- `DYNAMIC_CONSTRAINTS=false`: rollback to fixed fallback constraints (`min_fwhm=80`, `min_plqy=10`) when user does not explicitly provide thresholds.

## uv Dependency Workflow
- Dependency source of truth: `pyproject.toml`
- Lockfile: `uv.lock` (commit to repository)
- Install exact locked deps: `uv sync --frozen`
- Add dependency: `uv add <package>`
- Refresh lockfile: `uv lock --upgrade`
- Export compatibility requirements: `uv export --format requirements-txt -o requirements.txt`
- Note: standardize on local `.venv` as the only virtual environment for this project.

## MVP Compatibility Contract
- Keep `find_white_light_candidates(min_fwhm, min_plqy, ...)` signature unchanged.
- Only change how `min_fwhm/min_plqy` are produced:
  - Planner parses user explicit constraints and leaves missing metrics as null.
  - ConstraintBuilder fills missing metrics using KG distributions (or fallback if rollback switch is off).
  - Retriever consumes final effective constraints.

See full project context and architecture details in `.github/copilot-instructions.md`.
