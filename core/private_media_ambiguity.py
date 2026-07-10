from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


class PrivateMediaAmbiguityError(Exception):
    def __init__(self, path: str, resources: list[Any], reason: str = ""):
        self.path = str(path or "")
        self.resources = list(resources)
        self.reason = reason or "multiple_physical_resources"
        super().__init__(
            f"Private media resolution is ambiguous: "
            f"path={self.path!r} reason={self.reason!r}"
        )


def _resource_instance(resource):
    for attr_name in (
        "obj",
        "object",
        "instance",
        "model_instance",
    ):
        value = getattr(resource, attr_name, None)
        if value is not None:
            return value
    return None


def _rule_value(rule, *names, default=None):
    if rule is None:
        return default

    for name in names:
        value = getattr(rule, name, None)
        if value not in (None, "", (), [], {}):
            return value

    return default


def _rule_field_name(rule) -> str:
    value = _rule_value(
        rule,
        "field_name",
        "file_field",
        "media_field",
        "field",
        default="",
    )

    if isinstance(value, str):
        return value

    return str(getattr(value, "name", "") or "")


def _model_label_from_rule(rule) -> str:
    value = _rule_value(
        rule,
        "model_label",
        default="",
    )

    if isinstance(value, str):
        return value

    meta = getattr(value, "_meta", None)
    return str(getattr(meta, "label", "") or "")


def private_media_physical_identity(resource):
    """
    Canonical identity for the physical database resource behind a media match.

    Proxy models that point to the same concrete table row and field column
    intentionally collapse to the same identity.
    """
    instance = _resource_instance(resource)
    rule = getattr(resource, "rule", None)

    if instance is None:
        return (
            "unresolved",
            _model_label_from_rule(rule).lower(),
            str(getattr(resource, "object_id", "") or ""),
            _rule_field_name(rule),
        )

    meta = instance._meta
    field_name = _rule_field_name(rule)

    field_column = field_name
    if field_name:
        try:
            field_column = meta.get_field(field_name).column
        except Exception:
            field_column = field_name

    return (
        "db",
        str(meta.db_table),
        str(getattr(instance, "pk", "") or ""),
        str(field_column or ""),
    )


def private_media_resource_identity(resource):
    rule = getattr(resource, "rule", None)
    instance = _resource_instance(resource)

    model_label = _model_label_from_rule(rule)
    if not model_label and instance is not None:
        model_label = str(instance._meta.label)

    return (
        str(
            _rule_value(
                rule,
                "key",
                "rule_key",
                "name",
                default="",
            )
            or ""
        ),
        model_label,
        str(
            getattr(resource, "object_id", None)
            or getattr(instance, "pk", None)
            or ""
        ),
        _rule_field_name(rule),
    )


def private_media_authorization_context(resource):
    """
    Best-effort authorization signature.

    This is used only when resolution finds multiple proxy-only aliases for the
    same physical row and no concrete-model match is available.
    """
    rule = getattr(resource, "rule", None)

    groups = _rule_value(
        rule,
        "groups",
        "group_names",
        "allowed_groups",
        default=(),
    ) or ()

    if isinstance(groups, str):
        groups = (groups,)

    return (
        str(_rule_value(rule, "scope", default="") or ""),
        str(
            _rule_value(
                rule,
                "permission",
                "view_permission",
                default="",
            )
            or ""
        ),
        tuple(sorted(str(group) for group in groups)),
    )


def _is_proxy_resource(resource) -> bool:
    instance = _resource_instance(resource)
    if instance is None:
        return False
    return bool(getattr(instance._meta, "proxy", False))


def _canonical_resource_for_alias_group(resources: list[Any]):
    """
    Choose the concrete-model resource when proxy aliases point to the same
    physical row.

    If no concrete resource exists, proxy-only aliases are allowed only when
    their authorization contexts are identical.
    """
    concrete_resources = [
        resource
        for resource in resources
        if not _is_proxy_resource(resource)
    ]

    if len(concrete_resources) == 1:
        return concrete_resources[0]

    if len(concrete_resources) > 1:
        contexts = {
            private_media_authorization_context(resource)
            for resource in concrete_resources
        }
        if len(contexts) > 1:
            raise PrivateMediaAmbiguityError(
                "",
                concrete_resources,
                reason="same_row_different_authorization_context",
            )
        return concrete_resources[0]

    contexts = {
        private_media_authorization_context(resource)
        for resource in resources
    }

    if len(contexts) > 1:
        raise PrivateMediaAmbiguityError(
            "",
            resources,
            reason="proxy_alias_authorization_context_mismatch",
        )

    return resources[0]


def collect_private_media_resource_groups(path: str):
    from core.private_media import iter_private_media_resources

    groups = defaultdict(list)

    for resource in iter_private_media_resources(path):
        identity = private_media_physical_identity(resource)

        # Avoid duplicate emission of the exact same rule/resource pair.
        exact_identity = private_media_resource_identity(resource)
        existing_exact = {
            private_media_resource_identity(item)
            for item in groups[identity]
        }

        if exact_identity not in existing_exact:
            groups[identity].append(resource)

    return groups


def collect_private_media_resources(path: str):
    """
    Return one canonical resource per physical database resource.
    """
    groups = collect_private_media_resource_groups(path)
    resources = []

    for group in groups.values():
        try:
            canonical = _canonical_resource_for_alias_group(group)
        except PrivateMediaAmbiguityError as exc:
            raise PrivateMediaAmbiguityError(
                path,
                exc.resources,
                reason=exc.reason,
            ) from exc

        resources.append(canonical)

    return resources


def resolve_private_media_resource_strict(path: str):
    """
    Resolve exactly one physical private resource.

    Proxy aliases of the same concrete row collapse to one canonical resource.
    Different physical rows sharing one storage path fail closed.
    """
    resources = collect_private_media_resources(path)

    if not resources:
        return None

    if len(resources) > 1:
        raise PrivateMediaAmbiguityError(
            path,
            resources,
            reason="multiple_physical_resources",
        )

    return resources[0]
