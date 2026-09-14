"""Read-only Ads deployment and schema readiness inspection."""

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from .meta_runtime import runtime_safety_snapshot


def inspect_ads_schema():
    """Return bounded schema state without applying or mutating migrations."""
    try:
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        leaves = sorted(name for app, name in loader.graph.leaf_nodes("ads"))
        applied = MigrationRecorder(connection).applied_migrations()
        missing = [name for name in leaves if ("ads", name) not in applied]
        return {"current": not missing, "expected": leaves, "missing": missing, "error": None}
    except Exception:
        return {"current": False, "expected": [], "missing": [], "error": "schema_inspection_unavailable"}


def deployment_readiness():
    schema = inspect_ads_schema()
    runtime = runtime_safety_snapshot()
    blockers = list(runtime["blockers"])
    if schema["error"]:
        blockers.append(schema["error"])
    elif schema["missing"]:
        blockers.append("ads_schema_outdated")
    return {
        "schema": schema,
        "runtime": runtime,
        "safe_to_start": not blockers,
        "blockers": blockers,
    }
