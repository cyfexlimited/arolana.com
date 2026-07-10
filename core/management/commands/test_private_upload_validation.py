from __future__ import annotations

import io
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand

from core.private_upload_validation import (
    validate_chat_attachment_upload,
    validate_kyc_upload,
    validate_payment_proof_upload,
    validate_resume_upload,
)


class Command(BaseCommand):
    help = (
        "Test Arolana private upload validation policies "
        "with safe and malicious test payloads."
    )

    def handle(
        self,
        *args,
        **options,
    ):
        passed = 0
        failed = 0

        cases = [
            (
                "valid minimal PDF",
                self._pdf_file(),
                validate_kyc_upload,
                True,
            ),
            (
                "EXE renamed as PDF",
                self._fake_exe_pdf(),
                validate_kyc_upload,
                False,
            ),
            (
                "HTML renamed as JPG",
                self._fake_html_jpg(),
                validate_payment_proof_upload,
                False,
            ),
            (
                "ZIP renamed as DOCX",
                self._fake_docx(),
                validate_resume_upload,
                False,
            ),
            (
                "valid minimal DOCX structure",
                self._valid_docx(),
                validate_chat_attachment_upload,
                True,
            ),
            (
                "SVG upload",
                self._svg_file(),
                validate_payment_proof_upload,
                False,
            ),
        ]

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Arolana Private Upload Validation Tests"
            )
        )

        for (
            name,
            uploaded_file,
            validator,
            should_pass,
        ) in cases:
            actual_pass = True
            error_text = ""

            try:
                validator(
                    uploaded_file
                )

            except ValidationError as exc:
                actual_pass = False
                error_text = "; ".join(
                    exc.messages
                )

            correct = (
                actual_pass
                == should_pass
            )

            if correct:
                passed += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"PASS: {name}"
                    )
                )

                if error_text:
                    self.stdout.write(
                        f"      rejected: {error_text}"
                    )

            else:
                failed += 1

                self.stdout.write(
                    self.style.ERROR(
                        f"FAIL: {name}"
                    )
                )

                self.stdout.write(
                    (
                        f"      expected_pass={should_pass} "
                        f"actual_pass={actual_pass} "
                        f"error={error_text}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            f"Passed: {passed}"
        )

        self.stdout.write(
            f"Failed: {failed}"
        )

        if failed:
            raise SystemExit(
                1
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Private upload validation tests passed."
            )
        )

    def _pdf_file(self):
        return SimpleUploadedFile(
            "identity.pdf",
            (
                b"%PDF-1.4\n"
                b"1 0 obj\n"
                b"<< /Type /Catalog >>\n"
                b"endobj\n"
                b"%%EOF\n"
            ),
            content_type="application/pdf",
        )

    def _fake_exe_pdf(self):
        return SimpleUploadedFile(
            "identity.pdf",
            b"MZ\x90\x00FAKE-EXECUTABLE",
            content_type="application/pdf",
        )

    def _fake_html_jpg(self):
        return SimpleUploadedFile(
            "proof.jpg",
            b"<html><script>alert(1)</script></html>",
            content_type="image/jpeg",
        )

    def _fake_docx(self):
        buffer = io.BytesIO()

        with zipfile.ZipFile(
            buffer,
            "w",
        ) as archive:
            archive.writestr(
                "random.txt",
                "Not a Word document",
            )

        return SimpleUploadedFile(
            "resume.docx",
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )

    def _valid_docx(self):
        buffer = io.BytesIO()

        with zipfile.ZipFile(
            buffer,
            "w",
        ) as archive:
            archive.writestr(
                "[Content_Types].xml",
                (
                    '<?xml version="1.0"?>'
                    "<Types></Types>"
                ),
            )

            archive.writestr(
                "word/document.xml",
                (
                    '<?xml version="1.0"?>'
                    "<document></document>"
                ),
            )

        return SimpleUploadedFile(
            "attachment.docx",
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )

    def _svg_file(self):
        return SimpleUploadedFile(
            "proof.svg",
            (
                b'<svg xmlns="http://www.w3.org/2000/svg">'
                b'<script>alert(1)</script>'
                b"</svg>"
            ),
            content_type="image/svg+xml",
        )