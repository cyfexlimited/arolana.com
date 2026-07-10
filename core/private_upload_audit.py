from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Iterable

from django.apps import apps
from django.db import models

from core.private_upload_registry import (
    EXPECTED_PRIVATE_UPLOAD_MAP,
    EXPECTED_PRIVATE_UPLOADS,
    EXPLICIT_PUBLIC_UPLOAD_IDENTITIES,
)


@dataclass(frozen=True)
class AuditFinding:
    level: str
    code: str
    message: str
    model_label: str = ""
    field_name: str = ""
    hint: str = ""

    @property
    def identity(self):
        if self.model_label and self.field_name:
            return f"{self.model_label}.{self.field_name}"
        return self.model_label or self.field_name or "-"


@dataclass
class AuditReport:
    rules_discovered: int = 0
    requirements_checked: int = 0
    fields_scanned: int = 0
    findings: list[AuditFinding] = dataclass_field(default_factory=list)

    @property
    def errors(self):
        return [finding for finding in self.findings if finding.level == "ERROR"]

    @property
    def warnings(self):
        return [finding for finding in self.findings if finding.level == "WARNING"]

    @property
    def passed(self):
        return not self.errors


def _normalize_policy_key(value: Any) -> str:
    if value is None:
        return ""

    if not isinstance(value, str):
        for attr_name in ("key", "name", "policy_key", "policy_name"):
            nested = getattr(value, attr_name, None)
            if isinstance(nested, str) and nested.strip():
                value = nested
                break
        else:
            value = str(value)

    return (
        str(value)
        .strip()
        .replace("-", "_")
        .replace(" ", "_")
        .upper()
    )


def _is_private_upload_validator(validator: Any) -> bool:
    try:
        from core.private_upload_validation import PrivateUploadValidator

        if isinstance(validator, PrivateUploadValidator):
            return True
    except Exception:
        pass

    validator_class = validator.__class__
    return (
        validator_class.__name__ == "PrivateUploadValidator"
        and validator_class.__module__.endswith("private_upload_validation")
    )


def _validator_policy_key(validator: Any) -> str:
    for attr_name in (
        "policy_key",
        "policy_name",
        "policy",
        "name",
        "key",
    ):
        value = getattr(validator, attr_name, None)
        normalized = _normalize_policy_key(value)
        if normalized and normalized != str(validator).upper():
            return normalized

    deconstruct = getattr(validator, "deconstruct", None)
    if callable(deconstruct):
        try:
            deconstructed = deconstruct()
        except Exception:
            deconstructed = None

        if isinstance(deconstructed, tuple):
            # Common shape: (path, args, kwargs)
            args = deconstructed[1] if len(deconstructed) > 1 else ()
            kwargs = deconstructed[2] if len(deconstructed) > 2 else {}

            for value in args or ():
                normalized = _normalize_policy_key(value)
                if normalized:
                    return normalized

            for key in (
                "policy_key",
                "policy_name",
                "policy",
                "name",
                "key",
            ):
                if key in (kwargs or {}):
                    normalized = _normalize_policy_key(kwargs[key])
                    if normalized:
                        return normalized

    return ""


def _field_private_validators(model_field: models.Field) -> list[Any]:
    return [
        validator
        for validator in getattr(model_field, "validators", ())
        if _is_private_upload_validator(validator)
    ]


def _container_items(value: Any, seen: set[int] | None = None) -> Iterable[Any]:
    """
    Recursively flatten ordinary registry containers so rules can be stored as:
    - a tuple/list/set of rules,
    - a dict of rules,
    - a dict of lists/tuples of rules.

    Arbitrary objects are yielded but not recursively inspected.
    """
    seen = seen or set()
    marker = id(value)

    if marker in seen:
        return

    seen.add(marker)
    yield value

    if isinstance(value, dict):
        for nested in value.values():
            yield from _container_items(nested, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            yield from _container_items(nested, seen)


def _discover_private_media_rules() -> list[Any]:
    # Delayed import avoids creating model-import cycles during app loading.
    from core import private_media

    try:
        PrivateMediaRule = private_media.PrivateMediaRule
    except AttributeError as exc:
        raise RuntimeError(
            "core.private_media.PrivateMediaRule is missing."
        ) from exc

    discovered = []
    seen_ids = set()

    for value in vars(private_media).values():
        for candidate in _container_items(value):
            if not isinstance(candidate, PrivateMediaRule):
                continue

            marker = id(candidate)
            if marker in seen_ids:
                continue

            seen_ids.add(marker)
            discovered.append(candidate)

    return discovered


def _value_as_model_label(value: Any) -> str:
    if isinstance(value, str):
        return value

    meta = getattr(value, "_meta", None)
    if meta is not None:
        return getattr(meta, "label", "") or ""

    return ""


def _rule_model_label(rule: Any) -> str:
    for attr_name in (
        "model_label",
        "model",
        "resource_model",
        "model_class",
    ):
        value = getattr(rule, attr_name, None)
        model_label = _value_as_model_label(value)
        if model_label:
            return model_label

    return ""


def _rule_field_name(rule: Any) -> str:
    for attr_name in (
        "field_name",
        "file_field",
        "media_field",
        "field",
    ):
        value = getattr(rule, attr_name, None)

        if isinstance(value, str) and value:
            return value

        if hasattr(value, "name"):
            name = getattr(value, "name", "")
            if isinstance(name, str) and name:
                return name

    return ""


def _rule_key(rule: Any) -> str:
    for attr_name in ("key", "rule_key", "name"):
        value = getattr(rule, attr_name, None)
        if isinstance(value, str) and value:
            return value
    return rule.__class__.__name__


def _rule_identity(rule: Any) -> tuple[str, str] | None:
    model_label = _rule_model_label(rule)
    field_name = _rule_field_name(rule)

    if not model_label or not field_name:
        return None

    return (model_label.lower(), field_name)


def _normalize_upload_root(upload_to: Any) -> str:
    if not isinstance(upload_to, str):
        return ""

    value = upload_to.strip().lstrip("/").replace("\\", "/")
    while "//" in value:
        value = value.replace("//", "/")

    return value.rstrip("/") + "/" if value else ""


def _known_private_roots() -> set[str]:
    roots = set()

    for requirement in EXPECTED_PRIVATE_UPLOADS:
        try:
            model = apps.get_model(requirement.model_label)
            model_field = model._meta.get_field(requirement.field_name)
        except (LookupError, models.FieldDoesNotExist):
            continue

        root = _normalize_upload_root(getattr(model_field, "upload_to", ""))
        if root:
            roots.add(root)

    return roots


def _path_is_under_root(path: str, root: str) -> bool:
    return bool(path and root and (path == root or path.startswith(root)))


def audit_private_upload_security(*, strict_all_fields: bool = False) -> AuditReport:
    report = AuditReport()

    try:
        private_rules = _discover_private_media_rules()
    except Exception as exc:
        report.findings.append(
            AuditFinding(
                level="ERROR",
                code="private_upload.E001",
                message=f"Could not discover private media rules: {exc}",
                hint=(
                    "Keep PrivateMediaRule instances in a module-level list, tuple, "
                    "set, or dict in core.private_media."
                ),
            )
        )
        return report

    report.rules_discovered = len(private_rules)

    if not private_rules:
        report.findings.append(
            AuditFinding(
                level="ERROR",
                code="private_upload.E002",
                message="No PrivateMediaRule instances were discovered.",
                hint="The private media rule registry must never be empty.",
            )
        )
        return report

    rule_by_identity = {}
    uninspectable_rules = []

    for rule in private_rules:
        identity = _rule_identity(rule)

        if identity is None:
            uninspectable_rules.append(rule)
            continue

        if identity in rule_by_identity:
            existing = rule_by_identity[identity]
            report.findings.append(
                AuditFinding(
                    level="ERROR",
                    code="private_upload.E003",
                    message=(
                        "Duplicate private media rules target the same model field: "
                        f"{_rule_key(existing)!r} and {_rule_key(rule)!r}."
                    ),
                    model_label=_rule_model_label(rule),
                    field_name=_rule_field_name(rule),
                    hint="Keep exactly one authorization rule per private upload field.",
                )
            )
            continue

        rule_by_identity[identity] = rule

    for rule in uninspectable_rules:
        report.findings.append(
            AuditFinding(
                level="ERROR",
                code="private_upload.E004",
                message=(
                    f"Private media rule {_rule_key(rule)!r} does not expose "
                    "an inspectable model label and field name."
                ),
                hint=(
                    "PrivateMediaRule must expose model_label/model and "
                    "field_name/file_field so the audit can verify coverage."
                ),
            )
        )

    # 1. Every private media rule must have an expected upload policy.
    for identity, rule in sorted(rule_by_identity.items()):
        if identity not in EXPECTED_PRIVATE_UPLOAD_MAP:
            report.findings.append(
                AuditFinding(
                    level="ERROR",
                    code="private_upload.E005",
                    message=(
                        f"Authorization rule {_rule_key(rule)!r} has no private "
                        "upload policy requirement."
                    ),
                    model_label=_rule_model_label(rule),
                    field_name=_rule_field_name(rule),
                    hint=(
                        "Add the field and its expected policy_key to "
                        "core.private_upload_registry.EXPECTED_PRIVATE_UPLOADS."
                    ),
                )
            )

    # 2. Every expected private upload must resolve to a real file field, carry
    #    the correct validator, and have an authorization rule.
    for requirement in EXPECTED_PRIVATE_UPLOADS:
        report.requirements_checked += 1
        identity = requirement.identity

        try:
            model = apps.get_model(requirement.model_label)
        except LookupError:
            report.findings.append(
                AuditFinding(
                    level="ERROR",
                    code="private_upload.E006",
                    message="Expected private upload model does not exist.",
                    model_label=requirement.model_label,
                    field_name=requirement.field_name,
                    hint="Fix or remove the stale private upload registry entry.",
                )
            )
            continue

        try:
            model_field = model._meta.get_field(requirement.field_name)
        except models.FieldDoesNotExist:
            report.findings.append(
                AuditFinding(
                    level="ERROR",
                    code="private_upload.E007",
                    message="Expected private upload field does not exist.",
                    model_label=requirement.model_label,
                    field_name=requirement.field_name,
                    hint="Fix or remove the stale private upload registry entry.",
                )
            )
            continue

        if not isinstance(model_field, models.FileField):
            report.findings.append(
                AuditFinding(
                    level="ERROR",
                    code="private_upload.E008",
                    message=(
                        f"Expected a FileField/ImageField, found "
                        f"{model_field.__class__.__name__}."
                    ),
                    model_label=requirement.model_label,
                    field_name=requirement.field_name,
                )
            )
            continue

        private_validators = _field_private_validators(model_field)

        if not private_validators:
            report.findings.append(
                AuditFinding(
                    level="ERROR",
                    code="private_upload.E009",
                    message="Private upload field has no PrivateUploadValidator.",
                    model_label=requirement.model_label,
                    field_name=requirement.field_name,
                    hint=(
                        f"Attach the validator for policy "
                        f"{requirement.policy_key} to the model field."
                    ),
                )
            )
        else:
            actual_policies = {
                _validator_policy_key(validator)
                for validator in private_validators
            }
            actual_policies.discard("")

            expected_policy = _normalize_policy_key(requirement.policy_key)

            if not actual_policies:
                report.findings.append(
                    AuditFinding(
                        level="ERROR",
                        code="private_upload.E010",
                        message=(
                            "PrivateUploadValidator is attached, but its policy "
                            "key could not be introspected."
                        ),
                        model_label=requirement.model_label,
                        field_name=requirement.field_name,
                        hint=(
                            "PrivateUploadValidator should expose policy_key, "
                            "policy_name, or a deconstruct() argument containing "
                            "the policy key."
                        ),
                    )
                )
            elif expected_policy not in actual_policies:
                report.findings.append(
                    AuditFinding(
                        level="ERROR",
                        code="private_upload.E011",
                        message=(
                            f"Wrong private upload policy. Expected "
                            f"{expected_policy}; found "
                            f"{', '.join(sorted(actual_policies))}."
                        ),
                        model_label=requirement.model_label,
                        field_name=requirement.field_name,
                        hint="Attach the correct policy validator to the model field.",
                    )
                )

        if identity not in rule_by_identity:
            report.findings.append(
                AuditFinding(
                    level="ERROR",
                    code="private_upload.E012",
                    message="Private upload field has no private media authorization rule.",
                    model_label=requirement.model_label,
                    field_name=requirement.field_name,
                    hint="Add a PrivateMediaRule for this model field.",
                )
            )

    # 3. Discover any field that has a private validator but is absent from the
    #    authorization/policy registry.
    known_private_roots = _known_private_roots()

    for model in apps.get_models():
        for model_field in model._meta.get_fields():
            if not isinstance(model_field, models.FileField):
                continue

            report.fields_scanned += 1
            identity = (model._meta.label.lower(), model_field.name)
            private_validators = _field_private_validators(model_field)
            upload_root = _normalize_upload_root(
                getattr(model_field, "upload_to", "")
            )

            if private_validators and identity not in EXPECTED_PRIVATE_UPLOAD_MAP:
                report.findings.append(
                    AuditFinding(
                        level="ERROR",
                        code="private_upload.E013",
                        message=(
                            "Field has PrivateUploadValidator but is not registered "
                            "in EXPECTED_PRIVATE_UPLOADS."
                        ),
                        model_label=model._meta.label,
                        field_name=model_field.name,
                        hint=(
                            "Register the policy requirement and add a matching "
                            "PrivateMediaRule."
                        ),
                    )
                )

            if private_validators and identity not in rule_by_identity:
                report.findings.append(
                    AuditFinding(
                        level="ERROR",
                        code="private_upload.E014",
                        message=(
                            "Field has PrivateUploadValidator but no private media "
                            "authorization rule."
                        ),
                        model_label=model._meta.label,
                        field_name=model_field.name,
                        hint="Add a matching PrivateMediaRule.",
                    )
                )

            under_known_private_root = any(
                _path_is_under_root(upload_root, root)
                for root in known_private_roots
                if upload_root
            )

            if (
                under_known_private_root
                and identity not in EXPECTED_PRIVATE_UPLOAD_MAP
            ):
                report.findings.append(
                    AuditFinding(
                        level="ERROR",
                        code="private_upload.E015",
                        message=(
                            f"Unregistered upload field uses a known private media "
                            f"root: {upload_root!r}."
                        ),
                        model_label=model._meta.label,
                        field_name=model_field.name,
                        hint=(
                            "Register it as private with the correct policy and "
                            "authorization rule, or move it to an explicitly public "
                            "upload root."
                        ),
                    )
                )

            if (
                strict_all_fields
                and identity not in EXPECTED_PRIVATE_UPLOAD_MAP
                and identity not in EXPLICIT_PUBLIC_UPLOAD_IDENTITIES
            ):
                report.findings.append(
                    AuditFinding(
                        level="ERROR",
                        code="private_upload.E016",
                        message=(
                            "Upload field is not explicitly classified as PUBLIC "
                            "or PRIVATE."
                        ),
                        model_label=model._meta.label,
                        field_name=model_field.name,
                        hint=(
                            "After human review, add the field either to "
                            "EXPECTED_PRIVATE_UPLOADS with a policy and authorization "
                            "rule, or to EXPLICIT_PUBLIC_UPLOADS."
                        ),
                    )
                )

    return report
