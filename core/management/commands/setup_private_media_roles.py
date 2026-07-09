from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from core.private_media import PRIVATE_MEDIA_RULES


class Command(BaseCommand):
    help = (
        "Create Arolana private-media authorization groups "
        "and attach the appropriate model view permissions."
    )

    def handle(self, *args, **options):
        created_groups = 0
        permission_links = 0
        missing_models = []
        missing_permissions = []

        processed_pairs = set()

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Arolana Private Media Roles"
            )
        )

        for rule in PRIVATE_MEDIA_RULES:
            try:
                model = apps.get_model(
                    rule.model_label
                )
            except LookupError:
                missing_models.append(
                    rule.model_label
                )
                continue

            if not model:
                missing_models.append(
                    rule.model_label
                )
                continue

            content_type = ContentType.objects.get_for_model(
                model,
                for_concrete_model=False,
            )

            codename = (
                f"view_{model._meta.model_name}"
            )

            permission = Permission.objects.filter(
                content_type=content_type,
                codename=codename,
            ).first()

            if not permission:
                missing_permissions.append(
                    (
                        rule.model_label,
                        codename,
                    )
                )
                continue

            for group_name in rule.staff_groups:
                pair = (
                    group_name,
                    permission.pk,
                )

                if pair in processed_pairs:
                    continue

                processed_pairs.add(
                    pair
                )

                group, created = Group.objects.get_or_create(
                    name=group_name
                )

                if created:
                    created_groups += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Created group: {group_name}"
                        )
                    )

                group.permissions.add(
                    permission
                )

                permission_links += 1

                self.stdout.write(
                    (
                        f"Linked {group_name} -> "
                        f"{rule.model_label}.{codename}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Summary"
            )
        )

        self.stdout.write(
            f"Groups created: {created_groups}"
        )

        self.stdout.write(
            f"Permission links added/confirmed: {permission_links}"
        )

        if missing_models:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Models not available:"
                )
            )

            for model_label in sorted(
                set(missing_models)
            ):
                self.stdout.write(
                    f"  - {model_label}"
                )

        if missing_permissions:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "View permissions not found:"
                )
            )

            for model_label, codename in sorted(
                set(missing_permissions)
            ):
                self.stdout.write(
                    f"  - {model_label}: {codename}"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Private media role setup complete."
            )
        )

        self.stdout.write(
            (
                "Important: this command does not automatically add users "
                "to groups. Assign authorised staff through Django admin."
            )
        )