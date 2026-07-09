from collections import Counter
from typing import Optional

from django.apps import apps
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db.models import FileField

from arolana_config.urls import (
    _clean_media_path,
    _is_private_media_path,
    _is_public_media_path,
)


STATUS_PUBLIC = "PUBLIC"
STATUS_PRIVATE = "PRIVATE"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_REVIEW = "REVIEW"
STATUS_MIXED = "MIXED"
STATUS_EMPTY = "EMPTY"


SENSITIVE_PATH_TERMS = {
    # Identity / KYC
    "kyc",
    "identity",
    "identification",
    "passport",
    "government-id",
    "government_id",
    "address-proof",
    "address_proof",
    "selfie-verification",
    "selfie_verification",

    # Business verification
    "cac",
    "certificate",
    "verification",
    "compliance",

    # Financial / payment evidence
    "payment-proof",
    "payment_proof",
    "payment-proofs",
    "payment_proofs",
    "bank-proof",
    "bank_proof",
    "transfer-proof",
    "transfer_proof",
    "receipt",
    "receipts",

    # Order/private evidence
    "order-evidence",
    "order_evidence",
    "delivery-proof",
    "delivery_proof",
    "evidence",

    # Private messaging
    "chat-attachments",
    "chat_attachments",
    "message-attachments",
    "message_attachments",

    # General sensitive naming
    "private",
    "protected",
    "confidential",
    "documents",
}


def classify_media_path(path: str) -> str:
    """
    Classify a storage path using the active Arolana media security policy.
    """
    cleaned_path = _clean_media_path(path)

    if not cleaned_path:
        return STATUS_UNKNOWN

    if _is_private_media_path(cleaned_path):
        return STATUS_PRIVATE

    if _is_public_media_path(cleaned_path):
        return STATUS_PUBLIC

    return STATUS_UNKNOWN


def upload_to_description(field: FileField) -> str:
    """
    Return a readable description of the FileField upload_to configuration.
    """
    upload_to = field.upload_to

    if callable(upload_to):
        module = getattr(
            upload_to,
            "__module__",
            upload_to.__class__.__module__,
        )

        name = getattr(
            upload_to,
            "__qualname__",
            upload_to.__class__.__qualname__,
        )

        return f"{module}.{name}"

    return str(upload_to or "")


def static_upload_prefix(field: FileField) -> str:
    """
    Extract a best-effort static prefix from string upload_to values.

    Examples:

        products/%Y/%m/
            -> products

        installers/kyc/%Y/%m/
            -> installers/kyc

    Callable upload paths return an empty string because their result depends
    on runtime logic.
    """
    upload_to = field.upload_to

    if callable(upload_to):
        return ""

    value = str(upload_to or "").strip()

    if not value:
        return ""

    value = value.replace("\\", "/").lstrip("/")

    markers = (
        "%Y",
        "%y",
        "%m",
        "%d",
        "{",
    )

    cut_positions = []

    for marker in markers:
        position = value.find(marker)

        if position >= 0:
            cut_positions.append(position)

    if cut_positions:
        value = value[:min(cut_positions)]

    return _clean_media_path(
        value.rstrip("/")
    )


def contains_sensitive_term(path: str) -> bool:
    """
    Detect sensitive-looking path segments.

    This is an audit warning layer only. Actual access control continues to be
    determined by the Arolana media security policy.
    """
    cleaned_path = _clean_media_path(path)

    if not cleaned_path:
        return False

    lowered = cleaned_path.lower()

    segments = {
        segment.strip()
        for segment in lowered.split("/")
        if segment.strip()
    }

    for term in SENSITIVE_PATH_TERMS:
        if term in segments:
            return True

    return False


def combine_statuses(
    statuses: set[str],
    declared_status: str,
) -> str:
    """
    Produce one field-level classification from declaration and live values.
    """
    meaningful = {
        status
        for status in statuses
        if status not in {
            STATUS_EMPTY,
            STATUS_REVIEW,
        }
    }

    if not meaningful:
        if declared_status in {
            STATUS_PUBLIC,
            STATUS_PRIVATE,
        }:
            return declared_status

        return STATUS_REVIEW

    if len(meaningful) == 1:
        return next(iter(meaningful))

    return STATUS_MIXED


class Command(BaseCommand):
    help = (
        "Audit every Django FileField and ImageField against Arolana's "
        "public/private media security policy."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            action="append",
            default=[],
            help=(
                "Limit audit to a model label. "
                "May be supplied multiple times. "
                "Example: --model installers.ProviderKYCDocument"
            ),
        )

        parser.add_argument(
            "--sample-size",
            type=int,
            default=5,
            help=(
                "Maximum number of live file paths to show per field. "
                "Default: 5."
            ),
        )

        parser.add_argument(
            "--check-storage",
            action="store_true",
            help=(
                "Check whether sampled file references physically exist "
                "in default_storage."
            ),
        )

        parser.add_argument(
            "--fail-on-unknown",
            action="store_true",
            help=(
                "Exit with an error when UNKNOWN, REVIEW, or MIXED fields "
                "are found."
            ),
        )

        parser.add_argument(
            "--only-problems",
            action="store_true",
            help=(
                "Show only UNKNOWN, REVIEW, MIXED, or suspicious fields."
            ),
        )

    def handle(self, *args, **options):
        model_filter = set(
            options["model"] or []
        )

        sample_size = max(
            1,
            min(
                int(options["sample_size"]),
                50,
            ),
        )

        check_storage = bool(
            options["check_storage"]
        )

        fail_on_unknown = bool(
            options["fail_on_unknown"]
        )

        only_problems = bool(
            options["only_problems"]
        )

        field_counts = Counter()
        live_path_counts = Counter()

        problem_count = 0
        critical_count = 0

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Arolana Media Security Audit"
            )
        )

        self.stdout.write(
            "=" * 80
        )

        self.stdout.write(
            "This command is read-only."
        )

        self.stdout.write(
            "It does not delete, move, publish, or modify media files."
        )

        self.stdout.write("")

        for model in apps.get_models():
            model_label = model._meta.label

            if (
                model_filter
                and model_label not in model_filter
            ):
                continue

            file_fields = [
                field
                for field in model._meta.fields
                if isinstance(field, FileField)
            ]

            if not file_fields:
                continue

            for field in file_fields:
                field_name = field.name

                upload_to_value = upload_to_description(
                    field
                )

                static_prefix = static_upload_prefix(
                    field
                )

                declared_status = (
                    classify_media_path(static_prefix)
                    if static_prefix
                    else STATUS_REVIEW
                )

                samples = []

                try:
                    qs = (
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
                        .only(
                            "pk",
                            field_name,
                        )
                    )

                    reference_count = qs.count()

                    for obj in qs[:sample_size]:
                        file_value = getattr(
                            obj,
                            field_name,
                            None,
                        )

                        name = _clean_media_path(
                            getattr(
                                file_value,
                                "name",
                                "",
                            )
                            or ""
                        )

                        if not name:
                            continue

                        status = classify_media_path(
                            name
                        )

                        sensitive = contains_sensitive_term(
                            name
                        )

                        storage_exists: Optional[bool] = None

                        if check_storage:
                            try:
                                storage_exists = (
                                    default_storage.exists(
                                        name
                                    )
                                )
                            except Exception:
                                storage_exists = None

                        samples.append(
                            {
                                "pk": obj.pk,
                                "name": name,
                                "status": status,
                                "sensitive": sensitive,
                                "exists": storage_exists,
                            }
                        )

                        live_path_counts[
                            status
                        ] += 1

                except Exception as exc:
                    reference_count = 0

                    samples.append(
                        {
                            "pk": None,
                            "name": (
                                f"ERROR READING FIELD: {exc}"
                            ),
                            "status": STATUS_UNKNOWN,
                            "sensitive": False,
                            "exists": None,
                        }
                    )

                sample_statuses = {
                    sample["status"]
                    for sample in samples
                }

                final_status = combine_statuses(
                    sample_statuses,
                    declared_status,
                )

                suspicious_public = any(
                    sample["status"] == STATUS_PUBLIC
                    and sample["sensitive"]
                    for sample in samples
                )

                has_missing_sample = any(
                    sample["exists"] is False
                    for sample in samples
                )

                is_problem = (
                    final_status
                    in {
                        STATUS_UNKNOWN,
                        STATUS_REVIEW,
                        STATUS_MIXED,
                    }
                    or suspicious_public
                    or has_missing_sample
                )

                is_critical = (
                    final_status == STATUS_MIXED
                    or suspicious_public
                )

                field_counts[
                    final_status
                ] += 1

                if is_problem:
                    problem_count += 1

                if is_critical:
                    critical_count += 1

                if (
                    only_problems
                    and not is_problem
                ):
                    continue

                self.stdout.write(
                    ""
                )

                status_text = (
                    f"[{final_status}] "
                    f"{model_label}.{field_name}"
                )

                if final_status == STATUS_PUBLIC:
                    self.stdout.write(
                        self.style.SUCCESS(
                            status_text
                        )
                    )

                elif final_status == STATUS_PRIVATE:
                    self.stdout.write(
                        self.style.HTTP_INFO(
                            status_text
                        )
                    )

                elif final_status == STATUS_MIXED:
                    self.stdout.write(
                        self.style.ERROR(
                            status_text
                        )
                    )

                else:
                    self.stdout.write(
                        self.style.WARNING(
                            status_text
                        )
                    )

                self.stdout.write(
                    f"  Field type: {field.__class__.__name__}"
                )

                self.stdout.write(
                    f"  upload_to: {upload_to_value or '(empty)'}"
                )

                self.stdout.write(
                    f"  Static prefix: {static_prefix or '(callable/dynamic)'}"
                )

                self.stdout.write(
                    f"  Declared status: {declared_status}"
                )

                self.stdout.write(
                    f"  Current references: {reference_count}"
                )

                if not samples:
                    self.stdout.write(
                        "  Samples: none"
                    )

                for sample in samples:
                    flags = []

                    if sample["sensitive"]:
                        flags.append(
                            "SENSITIVE-NAME"
                        )

                    if sample["exists"] is True:
                        flags.append(
                            "EXISTS"
                        )

                    elif sample["exists"] is False:
                        flags.append(
                            "MISSING"
                        )

                    flag_text = (
                        f" [{' '.join(flags)}]"
                        if flags
                        else ""
                    )

                    self.stdout.write(
                        (
                            f"  Sample pk={sample['pk']}: "
                            f"{sample['name']} "
                            f"-> {sample['status']}"
                            f"{flag_text}"
                        )
                    )

                if suspicious_public:
                    self.stdout.write(
                        self.style.ERROR(
                            "  CRITICAL: sensitive-looking path is currently PUBLIC."
                        )
                    )

                if final_status == STATUS_MIXED:
                    self.stdout.write(
                        self.style.ERROR(
                            "  CRITICAL: one field contains media with mixed visibility."
                        )
                    )

                if has_missing_sample:
                    self.stdout.write(
                        self.style.WARNING(
                            "  WARNING: at least one sampled DB reference is missing from storage."
                        )
                    )

        self.stdout.write("")
        self.stdout.write(
            "=" * 80
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Audit Summary"
            )
        )

        for status in (
            STATUS_PUBLIC,
            STATUS_PRIVATE,
            STATUS_UNKNOWN,
            STATUS_REVIEW,
            STATUS_MIXED,
        ):
            self.stdout.write(
                f"{status} fields: {field_counts[status]}"
            )

        self.stdout.write(
            f"Problem fields: {problem_count}"
        )

        self.stdout.write(
            f"Critical fields: {critical_count}"
        )

        self.stdout.write("")

        self.stdout.write(
            "Sampled live paths:"
        )

        for status in (
            STATUS_PUBLIC,
            STATUS_PRIVATE,
            STATUS_UNKNOWN,
        ):
            self.stdout.write(
                f"  {status}: {live_path_counts[status]}"
            )

        if critical_count:
            self.stdout.write(
                ""
            )

            self.stdout.write(
                self.style.ERROR(
                    "SECURITY ACTION REQUIRED: critical media-policy conflicts were found."
                )
            )

        elif problem_count:
            self.stdout.write(
                ""
            )

            self.stdout.write(
                self.style.WARNING(
                    "Review required: some media fields are not explicitly classified."
                )
            )

        else:
            self.stdout.write(
                ""
            )

            self.stdout.write(
                self.style.SUCCESS(
                    "All discovered media fields are classified cleanly."
                )
            )

        if (
            fail_on_unknown
            and problem_count
        ):
            raise CommandError(
                (
                    "Media security audit failed: "
                    f"{problem_count} problem field(s), "
                    f"{critical_count} critical field(s)."
                )
            )