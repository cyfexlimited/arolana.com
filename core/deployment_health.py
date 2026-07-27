import json
import logging
import os
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connection
from django.db.migrations.executor import MigrationExecutor


logger = logging.getLogger(__name__)


CRITICAL_MODEL_LABELS = (
    "core.SiteSettings",
    "core.HomePageAppearance",
    "homepage.HomepageBanner",
    "homepage.HomepageSection",
    "homepage.HomepageCategory",
    "footer_menu.FooterMenuCategory",
    "products.Category",
    "products.Product",
)

REQUIRED_SINGLETON_LABELS = (
    "core.SiteSettings",
    "core.HomePageAppearance",
)


def _safe_database_identity():
    database_settings = connection.settings_dict
    return {
        "alias": DEFAULT_DB_ALIAS,
        "engine": database_settings.get("ENGINE", ""),
        "host": database_settings.get("HOST") or "local/default",
        "name": str(database_settings.get("NAME") or ""),
    }


def _configured_environment():
    return str(
        getattr(settings, "AROLANA_DEPLOYMENT_ENVIRONMENT", "")
        or os.environ.get("RAILWAY_ENVIRONMENT")
        or ("local" if settings.DEBUG else "production")
    )


def _check_database(checks):
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    checks["database"] = {"ok": True, **_safe_database_identity()}


def _check_migrations(checks):
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    pending_plan = executor.migration_plan(targets)
    pending = [f"{migration.app_label}.{migration.name}" for migration, _ in pending_plan]
    checks["migrations"] = {
        "ok": not pending,
        "pending_count": len(pending),
        "pending": pending[:10],
    }
    if pending:
        raise RuntimeError("required migrations are not applied")


def _check_critical_configuration(checks):
    config_checks = {}
    missing_required = []

    for model_label in CRITICAL_MODEL_LABELS:
        model = apps.get_model(model_label)
        row = model.objects.order_by("pk").only("pk").first()
        table_info = {"ok": True, "first_id": getattr(row, "pk", None)}
        if model_label in REQUIRED_SINGLETON_LABELS and row is None:
            table_info["ok"] = False
            missing_required.append(model_label)
        config_checks[model_label] = table_info

    checks["critical_configuration"] = {
        "ok": not missing_required,
        "models": config_checks,
        "missing_required": missing_required,
    }
    if missing_required:
        raise RuntimeError("required configuration records are missing")


def _check_cache(checks):
    required = bool(getattr(settings, "AROLANA_CACHE_REQUIRED", False))
    key = "deployment:readiness:cache"

    if not required:
        checks["cache"] = {"ok": True, "required": False}
        return

    cache.set(key, "ok", 15)
    value = cache.get(key)
    cache.delete(key)

    checks["cache"] = {"ok": value == "ok", "required": True}
    if value != "ok":
        raise RuntimeError("required cache is not reachable")


def _check_media_storage(checks):
    required = bool(getattr(settings, "AROLANA_MEDIA_STORAGE_REQUIRED", False))
    storage_backend = (
        getattr(settings, "STORAGES", {})
        .get("default", {})
        .get("BACKEND", "")
    )

    if not required:
        checks["media_storage"] = {
            "ok": True,
            "required": False,
            "backend": storage_backend,
        }
        return

    if storage_backend == "django.core.files.storage.FileSystemStorage":
        media_root = Path(settings.MEDIA_ROOT)
        ok = media_root.exists() and media_root.is_dir() and os.access(media_root, os.R_OK | os.W_OK)
        checks["media_storage"] = {
            "ok": ok,
            "required": True,
            "backend": storage_backend,
            "path": str(media_root),
        }
        if not ok:
            raise RuntimeError("required filesystem media path is not accessible")
        return

    # Remote media is considered configured when the required bucket and endpoint
    # settings are present; object access is checked by normal media requests.
    ok = bool(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") and getattr(settings, "AWS_S3_ENDPOINT_URL", ""))
    checks["media_storage"] = {
        "ok": ok,
        "required": True,
        "backend": storage_backend,
        "bucket_configured": bool(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")),
        "endpoint_configured": bool(getattr(settings, "AWS_S3_ENDPOINT_URL", "")),
    }
    if not ok:
        raise RuntimeError("required remote media storage is not configured")


def _check_environment_isolation(checks):
    environment = _configured_environment().lower()
    public_domain = str(os.environ.get("RAILWAY_PUBLIC_DOMAIN", "") or "").lower()
    site_url = str(getattr(settings, "SITE_URL", "") or "").lower()
    media_url = str(getattr(settings, "MEDIA_URL", "") or "").lower()
    public_media_url = str(getattr(settings, "AROLANA_PUBLIC_MEDIA_BASE_URL", "") or "").lower()
    cache_key_prefix = str(getattr(settings, "AROLANA_CACHE_KEY_PREFIX", "") or "")
    bucket_name = str(getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "").lower()
    non_production = environment not in {"production", "prod", ""}
    problems = []

    if cache_key_prefix and environment and environment not in cache_key_prefix.lower():
        problems.append("cache key prefix does not include deployment environment")

    if non_production and public_domain:
        production_domain = "arolana.com"
        if site_url and production_domain in site_url and public_domain not in site_url:
            problems.append("SITE_URL points at production domain from non-production environment")
        if public_media_url and production_domain in public_media_url and public_domain not in public_media_url:
            problems.append("public media base URL points at production domain from non-production environment")

    if (
        non_production
        and bucket_name
        and not getattr(settings, "AROLANA_ALLOW_SHARED_MEDIA_STORAGE", False)
        and environment not in bucket_name
    ):
        problems.append("remote media bucket is not environment-specific")

    checks["environment_isolation"] = {
        "ok": not problems,
        "environment": environment,
        "public_domain": public_domain,
        "site_url_configured": bool(site_url),
        "media_url_configured": bool(media_url),
        "public_media_url_configured": bool(public_media_url),
        "cache_key_prefix": cache_key_prefix,
        "remote_media_bucket_configured": bool(bucket_name),
        "problems": problems,
    }
    if problems:
        raise RuntimeError("deployment environment isolation is not ready")


def readiness_status():
    checks = {}
    payload = {
        "status": "ready",
        "environment": _configured_environment(),
        "database": _safe_database_identity(),
        "checks": checks,
    }

    try:
        _check_database(checks)
        _check_migrations(checks)
        _check_critical_configuration(checks)
        _check_cache(checks)
        _check_media_storage(checks)
        _check_environment_isolation(checks)
    except Exception as exc:
        payload["status"] = "not_ready"
        payload["reason"] = exc.__class__.__name__
        payload["message"] = str(exc)
        logger.warning("deployment_readiness %s", json.dumps(payload, default=str))
        return False, payload

    logger.info("deployment_readiness %s", json.dumps(payload, default=str))
    return True, payload
