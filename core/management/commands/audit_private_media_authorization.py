from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from core.private_media import (
    PRIVATE_MEDIA_RULES,
    authorize_private_media_request,
    iter_private_media_resources,
    resource_owner_user_ids,
)


STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"


def make_request(
    factory: RequestFactory,
    path: str,
    user,
):
    """
    Build a secure request for direct authorization testing.

    This does not stream or download the storage object.
    It exercises the authorization decision layer only.
    """
    request = factory.get(
        f"/media/{path}",
        secure=True,
        HTTP_HOST="arolana.com",
    )

    request.user = user

    # Some private-media rules may inspect request.session.
    # For ordinary ownership and role tests there is no matching guest
    # session, so provide an empty session-like object.
    request.session = SimpleNamespace(
        session_key=None,
    )

    return request


def get_model_for_rule(rule):
    try:
        return apps.get_model(
            rule.model_label
        )
    except LookupError:
        return None


def get_sample_object(
    model,
    field_name: str,
):
    """
    Return one object containing a real file reference for the field.
    """
    try:
        return (
            model._default_manager
            .exclude(
                **{
                    f"{field_name}__isnull": True,
                }
            )
            .exclude(
                **{
                    field_name: "",
                }
            )
            .first()
        )
    except Exception:
        return None


def get_file_path(
    obj,
    field_name: str,
) -> str:
    if obj is None:
        return ""

    try:
        file_value = getattr(
            obj,
            field_name,
            None,
        )
    except Exception:
        return ""

    return str(
        getattr(
            file_value,
            "name",
            "",
        )
        or ""
    ).strip()


def view_permission_parts(model):
    content_type = ContentType.objects.get_for_model(
        model,
        for_concrete_model=False,
    )

    codename = (
        f"view_{model._meta.model_name}"
    )

    full_permission = (
        f"{model._meta.app_label}.{codename}"
    )

    return (
        content_type,
        codename,
        full_permission,
    )


def group_has_permission(
    group,
    content_type,
    codename: str,
) -> bool:
    return group.permissions.filter(
        content_type=content_type,
        codename=codename,
    ).exists()


def all_private_media_group_names() -> set[str]:
    names = set()

    for rule in PRIVATE_MEDIA_RULES:
        names.update(
            rule.staff_groups
        )

    return names


class Command(BaseCommand):
    help = (
        "Audit Arolana private-media authorization rules, ownership, "
        "role permissions, anonymous denial, unrelated-user denial, "
        "and superuser access."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-problems",
            action="store_true",
            help=(
                "Show only failed checks and important skips."
            ),
        )

        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help=(
                "Exit with a non-zero status when any authorization "
                "failure is detected."
            ),
        )

    def handle(self, *args, **options):
        only_problems = bool(
            options["only_problems"]
        )

        fail_on_error = bool(
            options["fail_on_error"]
        )

        factory = RequestFactory()

        User = get_user_model()

        counts = Counter()

        all_group_names = (
            all_private_media_group_names()
        )

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Arolana Private Media Authorization Audit"
            )
        )

        self.stdout.write(
            "=" * 80
        )

        self.stdout.write(
            "This command is read-only."
        )

        self.stdout.write(
            "It does not modify users, groups, permissions, "
            "database records, or media files."
        )

        self.stdout.write("")

        for rule in PRIVATE_MEDIA_RULES:
            rule_failures = []
            rule_passes = []
            rule_skips = []

            model = get_model_for_rule(
                rule
            )

            if model is None:
                rule_failures.append(
                    f"Model not found: {rule.model_label}"
                )

                self._render_rule(
                    rule,
                    rule_passes,
                    rule_failures,
                    rule_skips,
                    only_problems,
                )

                counts[STATUS_FAIL] += 1
                continue

            # ================================================================
            # PERMISSION METADATA
            # ================================================================

            (
                content_type,
                codename,
                full_permission,
            ) = view_permission_parts(
                model
            )

            # ================================================================
            # REQUIRED ROLE PERMISSION TESTS
            # ================================================================

            for group_name in rule.staff_groups:
                group = Group.objects.filter(
                    name=group_name
                ).first()

                if group is None:
                    rule_failures.append(
                        f"Missing required group: {group_name}"
                    )
                    continue

                if not group_has_permission(
                    group,
                    content_type,
                    codename,
                ):
                    rule_failures.append(
                        (
                            f"Required group '{group_name}' is missing "
                            f"permission {full_permission}"
                        )
                    )
                else:
                    rule_passes.append(
                        (
                            f"Required role permission: "
                            f"{group_name} -> {full_permission}"
                        )
                    )

            # ================================================================
            # CROSS-ROLE STATIC ISOLATION
            #
            # A group not configured for this rule must not accidentally hold
            # the model view permission.
            # ================================================================

            wrong_group_names = (
                all_group_names
                - set(rule.staff_groups)
            )

            for group_name in sorted(
                wrong_group_names
            ):
                group = Group.objects.filter(
                    name=group_name
                ).first()

                if group is None:
                    continue

                if group_has_permission(
                    group,
                    content_type,
                    codename,
                ):
                    rule_failures.append(
                        (
                            f"CROSS-ROLE LEAK: '{group_name}' unexpectedly "
                            f"has {full_permission}"
                        )
                    )

            if not any(
                message.startswith(
                    "CROSS-ROLE LEAK"
                )
                for message in rule_failures
            ):
                rule_passes.append(
                    "Cross-role permission isolation"
                )

            # ================================================================
            # SAMPLE RESOURCE
            # ================================================================

            sample_obj = get_sample_object(
                model,
                rule.field_name,
            )

            sample_path = get_file_path(
                sample_obj,
                rule.field_name,
            )

            if not sample_obj or not sample_path:
                rule_skips.append(
                    (
                        "No live file reference exists for runtime "
                        "ownership tests."
                    )
                )

                self._render_rule(
                    rule,
                    rule_passes,
                    rule_failures,
                    rule_skips,
                    only_problems,
                )

                if rule_failures:
                    counts[STATUS_FAIL] += 1
                else:
                    counts[STATUS_PASS] += 1
                    counts[STATUS_SKIP] += 1

                continue

            # ================================================================
            # DATABASE RESOURCE RESOLUTION
            # ================================================================

            matching_resources = [
                resource
                for resource
                in iter_private_media_resources(
                    sample_path
                )
                if (
                    resource.rule.key
                    == rule.key
                    and getattr(
                        resource.obj,
                        "pk",
                        None,
                    )
                    == sample_obj.pk
                )
            ]

            if not matching_resources:
                rule_failures.append(
                    (
                        "Live file could not resolve back to its "
                        "registered database resource."
                    )
                )

                self._render_rule(
                    rule,
                    rule_passes,
                    rule_failures,
                    rule_skips,
                    only_problems,
                    sample_path=sample_path,
                )

                counts[STATUS_FAIL] += 1
                continue

            resource = matching_resources[0]

            rule_passes.append(
                (
                    f"Database resource resolution: "
                    f"object_id={sample_obj.pk}"
                )
            )

            owner_ids = resource_owner_user_ids(
                resource
            )

            # ================================================================
            # ANONYMOUS DENIAL
            # ================================================================

            anonymous_request = make_request(
                factory,
                sample_path,
                AnonymousUser(),
            )

            anonymous_decision = (
                authorize_private_media_request(
                    anonymous_request,
                    sample_path,
                )
            )

            if anonymous_decision.allowed:
                rule_failures.append(
                    "Anonymous user was incorrectly allowed."
                )
            else:
                rule_passes.append(
                    (
                        "Anonymous denied: "
                        f"{anonymous_decision.reason}"
                    )
                )

            # ================================================================
            # OWNER / PARTICIPANT ACCESS
            # ================================================================

            if owner_ids:
                owner = (
                    User.objects
                    .filter(
                        pk__in=owner_ids,
                        is_active=True,
                    )
                    .first()
                )

                if owner is None:
                    rule_skips.append(
                        (
                            "Owner IDs resolved, but no active owner user "
                            "was available for runtime testing."
                        )
                    )

                else:
                    owner_request = make_request(
                        factory,
                        sample_path,
                        owner,
                    )

                    owner_decision = (
                        authorize_private_media_request(
                            owner_request,
                            sample_path,
                        )
                    )

                    if owner_decision.allowed:
                        rule_passes.append(
                            (
                                f"Owner/participant allowed: "
                                f"user_id={owner.pk}, "
                                f"reason={owner_decision.reason}"
                            )
                        )
                    else:
                        rule_failures.append(
                            (
                                f"Owner user {owner.pk} was denied: "
                                f"{owner_decision.reason}"
                            )
                        )

            else:
                rule_skips.append(
                    (
                        "No owner/participant user ID resolved for "
                        "this sample resource."
                    )
                )

            # ================================================================
            # UNRELATED USER DENIAL
            #
            # Try active non-superusers until one is found that the actual
            # authorization engine denies.
            # ================================================================

            candidate_queryset = (
                User.objects
                .filter(
                    is_active=True,
                    is_superuser=False,
                )
                .exclude(
                    pk__in=owner_ids,
                )
                .order_by(
                    "pk"
                )
            )

            denied_unrelated_user = None
            unexpectedly_allowed_users = []

            for candidate in candidate_queryset[:100]:
                candidate_request = make_request(
                    factory,
                    sample_path,
                    candidate,
                )

                candidate_decision = (
                    authorize_private_media_request(
                        candidate_request,
                        sample_path,
                    )
                )

                if not candidate_decision.allowed:
                    denied_unrelated_user = (
                        candidate,
                        candidate_decision,
                    )
                    break

                unexpectedly_allowed_users.append(
                    (
                        candidate.pk,
                        candidate_decision.reason,
                    )
                )

            if denied_unrelated_user:
                candidate, decision = (
                    denied_unrelated_user
                )

                rule_passes.append(
                    (
                        f"Unrelated user denied: "
                        f"user_id={candidate.pk}, "
                        f"reason={decision.reason}"
                    )
                )

            elif candidate_queryset.exists():
                rule_failures.append(
                    (
                        "Could not find any unrelated user who was denied. "
                        f"Allowed candidates={unexpectedly_allowed_users[:10]}"
                    )
                )

            else:
                rule_skips.append(
                    "No unrelated active user was available."
                )

            # ================================================================
            # SUPERUSER ACCESS
            # ================================================================

            superuser = (
                User.objects
                .filter(
                    is_active=True,
                    is_superuser=True,
                )
                .first()
            )

            if superuser is None:
                rule_skips.append(
                    "No active superuser available for runtime test."
                )

            else:
                superuser_request = make_request(
                    factory,
                    sample_path,
                    superuser,
                )

                superuser_decision = (
                    authorize_private_media_request(
                        superuser_request,
                        sample_path,
                    )
                )

                if superuser_decision.allowed:
                    rule_passes.append(
                        (
                            f"Superuser allowed: "
                            f"user_id={superuser.pk}"
                        )
                    )
                else:
                    rule_failures.append(
                        (
                            f"Superuser {superuser.pk} was denied: "
                            f"{superuser_decision.reason}"
                        )
                    )

            # ================================================================
            # RUNTIME ROLE MEMBER TESTS
            #
            # Groups may intentionally be empty during initial setup.
            # Static permission linkage is still tested above.
            # ================================================================

            for group_name in rule.staff_groups:
                group = Group.objects.filter(
                    name=group_name
                ).first()

                if group is None:
                    continue

                member = (
                    User.objects
                    .filter(
                        groups=group,
                        is_active=True,
                        is_superuser=False,
                    )
                    .exclude(
                        pk__in=owner_ids,
                    )
                    .first()
                )

                if member is None:
                    rule_skips.append(
                        (
                            f"No non-owner runtime member in "
                            f"'{group_name}'"
                        )
                    )
                    continue

                # Fetch a fresh User instance so permission caching cannot
                # affect the result.
                member = User.objects.get(
                    pk=member.pk
                )

                role_request = make_request(
                    factory,
                    sample_path,
                    member,
                )

                role_decision = (
                    authorize_private_media_request(
                        role_request,
                        sample_path,
                    )
                )

                if role_decision.allowed:
                    rule_passes.append(
                        (
                            f"Role member allowed: "
                            f"{group_name}, "
                            f"user_id={member.pk}, "
                            f"reason={role_decision.reason}"
                        )
                    )
                else:
                    rule_failures.append(
                        (
                            f"Authorized role member denied: "
                            f"group={group_name}, "
                            f"user_id={member.pk}, "
                            f"reason={role_decision.reason}"
                        )
                    )

            self._render_rule(
                rule,
                rule_passes,
                rule_failures,
                rule_skips,
                only_problems,
                sample_path=sample_path,
            )

            if rule_failures:
                counts[STATUS_FAIL] += 1
            else:
                counts[STATUS_PASS] += 1

            if rule_skips:
                counts[STATUS_SKIP] += 1

        # ====================================================================
        # SUMMARY
        # ====================================================================

        self.stdout.write("")
        self.stdout.write(
            "=" * 80
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Authorization Audit Summary"
            )
        )

        self.stdout.write(
            f"Rules checked: {len(PRIVATE_MEDIA_RULES)}"
        )

        self.stdout.write(
            f"Passed rules: {counts[STATUS_PASS]}"
        )

        self.stdout.write(
            f"Failed rules: {counts[STATUS_FAIL]}"
        )

        self.stdout.write(
            (
                f"Rules with skipped runtime checks: "
                f"{counts[STATUS_SKIP]}"
            )
        )

        if counts[STATUS_FAIL]:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(
                    "Private media authorization audit FAILED."
                )
            )

            if fail_on_error:
                raise CommandError(
                    (
                        "Private media authorization audit found "
                        f"{counts[STATUS_FAIL]} failing rule(s)."
                    )
                )

        else:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "Private media authorization audit passed."
                )
            )

    def _render_rule(
        self,
        rule,
        passes,
        failures,
        skips,
        only_problems,
        sample_path="",
    ):
        if only_problems and not failures:
            return

        self.stdout.write("")

        if failures:
            self.stdout.write(
                self.style.ERROR(
                    f"[FAIL] {rule.key}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[PASS] {rule.key}"
                )
            )

        self.stdout.write(
            f"  Model: {rule.model_label}"
        )

        self.stdout.write(
            f"  Field: {rule.field_name}"
        )

        self.stdout.write(
            f"  Scope: {rule.scope}"
        )

        if sample_path:
            self.stdout.write(
                f"  Sample: {sample_path}"
            )

        for message in passes:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  PASS: {message}"
                )
            )

        for message in failures:
            self.stdout.write(
                self.style.ERROR(
                    f"  FAIL: {message}"
                )
            )

        for message in skips:
            self.stdout.write(
                self.style.WARNING(
                    f"  SKIP: {message}"
                )
            )