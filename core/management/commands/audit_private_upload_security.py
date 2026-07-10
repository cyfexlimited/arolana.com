from django.core.management.base import BaseCommand, CommandError

from core.private_upload_audit import audit_private_upload_security


class Command(BaseCommand):
    help = (
        "Audit Arolana private upload fields, policy validators, "
        "private media authorization rules, and private upload roots."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Exit non-zero when one or more audit errors are found.",
        )
        parser.add_argument(
            "--only-problems",
            action="store_true",
            help="Hide the successful summary details and print only findings.",
        )
        parser.add_argument(
            "--strict-all-fields",
            action="store_true",
            help=(
                "Fail every FileField/ImageField that is not explicitly "
                "classified PUBLIC or PRIVATE."
            ),
        )

    def handle(self, *args, **options):
        report = audit_private_upload_security(
            strict_all_fields=options["strict_all_fields"],
        )
        only_problems = options["only_problems"]

        self.stdout.write("")
        self.stdout.write("Arolana Private Upload Security Audit")
        self.stdout.write("=" * 80)
        self.stdout.write(
            "This command is read-only. It does not modify database records or media files."
        )
        self.stdout.write("")

        if report.findings:
            for finding in report.findings:
                writer = (
                    self.stderr.write
                    if finding.level == "ERROR"
                    else self.stdout.write
                )

                writer(
                    f"[{finding.level}] {finding.code} "
                    f"{finding.identity}: {finding.message}"
                )

                if finding.hint:
                    writer(f"  Hint: {finding.hint}")

                writer("")
        elif only_problems:
            self.stdout.write("No private upload security problems found.")

        self.stdout.write("=" * 80)
        self.stdout.write("Audit Summary")
        self.stdout.write(f"Private media rules discovered: {report.rules_discovered}")
        self.stdout.write(
            f"Private upload requirements checked: {report.requirements_checked}"
        )
        self.stdout.write(f"File/Image fields scanned: {report.fields_scanned}")
        self.stdout.write(f"Errors: {len(report.errors)}")
        self.stdout.write(f"Warnings: {len(report.warnings)}")

        if report.passed:
            self.stdout.write(
                self.style.SUCCESS("Private upload security audit passed.")
            )
            return

        self.stdout.write(
            self.style.ERROR("Private upload security audit FAILED.")
        )

        if options["fail_on_error"]:
            raise CommandError(
                f"Private upload security audit found "
                f"{len(report.errors)} error(s)."
            )
