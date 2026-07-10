from collections import defaultdict

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from core.private_upload_registry import EXPECTED_PRIVATE_UPLOADS


def _physical_identity(model, model_field, object_id):
    """
    Proxy models collapse to the same underlying table row + field column.
    """
    return (
        model._meta.db_table,
        str(object_id),
        str(model_field.column),
    )


class Command(BaseCommand):
    help = (
        "Audit private upload references for one storage path referenced by "
        "multiple distinct physical database resources. Proxy aliases of the "
        "same row are reported separately but are not treated as ambiguity."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Exit non-zero when true physical ambiguity is found.",
        )
        parser.add_argument(
            "--show-aliases",
            action="store_true",
            help="Show paths represented through multiple proxy/model aliases.",
        )

    def handle(self, *args, **options):
        references = defaultdict(list)
        scanned_references = 0

        for requirement in EXPECTED_PRIVATE_UPLOADS:
            try:
                model = apps.get_model(requirement.model_label)
            except LookupError:
                raise CommandError(
                    f"Model not found: {requirement.model_label}"
                )

            try:
                model_field = model._meta.get_field(
                    requirement.field_name
                )
            except models.FieldDoesNotExist:
                raise CommandError(
                    f"Field not found: "
                    f"{requirement.model_label}.{requirement.field_name}"
                )

            if not isinstance(model_field, models.FileField):
                raise CommandError(
                    f"Not a FileField/ImageField: "
                    f"{requirement.model_label}.{requirement.field_name}"
                )

            queryset = (
                model.objects
                .exclude(**{f"{requirement.field_name}__isnull": True})
                .exclude(**{requirement.field_name: ""})
                .values_list("pk", requirement.field_name)
                .iterator(chunk_size=1000)
            )

            for object_id, path in queryset:
                normalized = str(path or "").strip().lstrip("/")
                if not normalized:
                    continue

                scanned_references += 1

                references[normalized].append(
                    {
                        "physical": _physical_identity(
                            model,
                            model_field,
                            object_id,
                        ),
                        "model_label": requirement.model_label,
                        "field_name": requirement.field_name,
                        "object_id": object_id,
                        "proxy": bool(model._meta.proxy),
                        "concrete_model": (
                            model._meta.concrete_model._meta.label
                        ),
                    }
                )

        ambiguous = {}
        aliases = {}

        for path, refs in references.items():
            physical_groups = defaultdict(list)

            for ref in refs:
                physical_groups[ref["physical"]].append(ref)

            if len(physical_groups) > 1:
                ambiguous[path] = physical_groups
            elif len(refs) > 1:
                aliases[path] = refs

        self.stdout.write("")
        self.stdout.write("Arolana Private Media Ambiguity Audit")
        self.stdout.write("=" * 80)
        self.stdout.write(
            "This command is read-only. It does not modify database rows or files."
        )
        self.stdout.write("")

        for path, groups in sorted(ambiguous.items()):
            self.stderr.write(
                self.style.ERROR(f"[AMBIGUOUS] {path}")
            )

            for physical, refs in groups.items():
                self.stderr.write(
                    f"  Physical resource: "
                    f"table={physical[0]} pk={physical[1]} column={physical[2]}"
                )
                for ref in refs:
                    self.stderr.write(
                        f"    - {ref['model_label']}."
                        f"{ref['field_name']} pk={ref['object_id']} "
                        f"proxy={ref['proxy']}"
                    )

            self.stderr.write("")

        if options["show_aliases"]:
            for path, refs in sorted(aliases.items()):
                self.stdout.write(f"[ALIAS] {path}")
                for ref in refs:
                    self.stdout.write(
                        f"  - {ref['model_label']}."
                        f"{ref['field_name']} pk={ref['object_id']} "
                        f"proxy={ref['proxy']} "
                        f"concrete={ref['concrete_model']}"
                    )
                self.stdout.write("")

        unique_physical_resources = set()
        for refs in references.values():
            for ref in refs:
                unique_physical_resources.add(ref["physical"])

        self.stdout.write("=" * 80)
        self.stdout.write("Ambiguity Audit Summary")
        self.stdout.write(
            f"Registry references scanned: {scanned_references}"
        )
        self.stdout.write(
            f"Unique private paths: {len(references)}"
        )
        self.stdout.write(
            f"Unique physical private resources: "
            f"{len(unique_physical_resources)}"
        )
        self.stdout.write(
            f"Proxy/model alias paths: {len(aliases)}"
        )
        self.stdout.write(
            f"Ambiguous physical paths: {len(ambiguous)}"
        )

        if ambiguous:
            self.stdout.write(
                self.style.ERROR(
                    "Private media ambiguity audit FAILED."
                )
            )

            if options["fail_on_error"]:
                raise CommandError(
                    f"{len(ambiguous)} ambiguous physical private path(s) found."
                )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Private media ambiguity audit passed."
            )
        )
