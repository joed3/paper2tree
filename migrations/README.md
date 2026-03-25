# Migrations

Scripts for migrating `outputs/` artifacts between schema versions.

## How schemas are versioned

`dag.json` artifacts carry a top-level `schema_version` integer that tracks the
project's **major version**. Only major releases can introduce breaking schema
changes, so only major bumps require a migration script.

The current schema version is **1** (project v1.x.x).

## Running a migration

Migrations are run from the project root:

```bash
python migrations/migrate_v0_to_v1.py
```

Each script is idempotent — re-running it on already-migrated files is safe.

## Writing a new migration

When a major release introduces breaking schema changes to `PaperDAG`,
`DAGNode`, `ClaimEvaluation`, or `PaperIndexEntry`:

1. Bump `SCHEMA_VERSION` in `src/schemas/output.py` and `version` in
   `pyproject.toml` / `frontend/package.json`.
2. Add an entry to `CHANGELOG.md` describing what changed.
3. Create `migrations/migrate_vN_to_vN+1.py`. Every migration script must:
   - Short-circuit if `dag["schema_version"] >= target` (idempotency).
   - Apply all field-level transforms.
   - Set `dag["schema_version"] = target` before writing.
   - Call `rebuild_index()` at the end to regenerate `outputs/index.json`.
4. Commit the migration script in the same PR as the schema change.

## History

| Script | Project versions | What changed |
|--------|-----------------|--------------|
| `migrate_v0_to_v1.py` | v0.x.x → v1.0.0 | `evaluation.validity_score` (float) → `evaluation.support_level` (high/medium/low); `summary.mean_validity_score` + `high_confidence_nodes` + `low_confidence_nodes` → `summary.high_support_nodes` + `low_support_nodes`; added top-level `schema_version` field |
