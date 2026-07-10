from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render

from vendors.models import VendorProfile

from .models import KYCDocument, KYCRecord


logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================


def _get_vendor_profile(request):
    """
    Safely return the authenticated user's vendor profile.

    Returns None when the user has not yet created a vendor profile.
    """
    try:
        return request.user.vendor_profile
    except (
        AttributeError,
        VendorProfile.DoesNotExist,
    ):
        return None


def _validation_error_messages(
    exc: ValidationError,
) -> list[str]:
    """
    Convert Django ValidationError into clean user-facing messages.
    """
    messages_list = []

    if hasattr(
        exc,
        "message_dict",
    ):
        for field_name, field_errors in exc.message_dict.items():
            for error in field_errors:
                messages_list.append(
                    str(error)
                )

    else:
        messages_list.extend(
            str(message)
            for message in exc.messages
        )

    return messages_list


# ============================================================================
# KYC DASHBOARD
# ============================================================================


@login_required
def kyc_dashboard(request):
    vendor = _get_vendor_profile(
        request
    )

    if vendor is None:
        return redirect(
            "vendors:become"
        )

    try:
        kyc_record = KYCRecord.objects.get(
            vendor=vendor
        )

    except KYCRecord.DoesNotExist:
        kyc_record = None

    documents = (
        KYCDocument.objects
        .filter(
            vendor=vendor
        )
        .order_by(
            "-uploaded_at"
        )
    )

    context = {
        "kyc_record": kyc_record,
        "documents": documents,
        "is_complete": (
            kyc_record.is_complete()
            if kyc_record
            else False
        ),
    }

    return render(
        request,
        "kyc/dashboard.html",
        context,
    )


# ============================================================================
# SUBMIT KYC INFORMATION
# ============================================================================


@login_required
def submit_kyc(request):
    vendor = _get_vendor_profile(
        request
    )

    if vendor is None:
        return redirect(
            "vendors:become"
        )

    try:
        kyc_record = KYCRecord.objects.get(
            vendor=vendor
        )

    except KYCRecord.DoesNotExist:
        kyc_record = KYCRecord(
            vendor=vendor
        )

    if request.method == "POST":
        fields = (
            "legal_business_name",
            "registration_number",
            "tax_id",
            "vat_number",
            "business_address",
            "city",
            "state",
            "country",
            "postal_code",
            "business_phone",
            "business_email",
            "website",
            "business_type",
            "authorized_person_name",
            "authorized_person_title",
            "authorized_person_email",
            "authorized_person_phone",
        )

        for field_name in fields:
            if field_name in request.POST:
                value = request.POST.get(
                    field_name,
                    "",
                ).strip()

                setattr(
                    kyc_record,
                    field_name,
                    value,
                )

        # Integer field handled separately.
        year_established = request.POST.get(
            "year_established",
            "",
        ).strip()

        if year_established:
            try:
                kyc_record.year_established = int(
                    year_established
                )

            except ValueError:
                messages.error(
                    request,
                    (
                        "Year established must be "
                        "a valid whole number."
                    ),
                )

                return render(
                    request,
                    "kyc/submit.html",
                    {
                        "kyc_record": kyc_record,
                    },
                )

        else:
            kyc_record.year_established = None

        kyc_record.kyc_status = "pending"

        try:
            # Validate model fields before saving.
            kyc_record.full_clean()

            with transaction.atomic():
                kyc_record.save()

        except ValidationError as exc:
            errors = _validation_error_messages(
                exc
            )

            for error in errors:
                messages.error(
                    request,
                    error,
                )

            return render(
                request,
                "kyc/submit.html",
                {
                    "kyc_record": kyc_record,
                },
            )

        messages.success(
            request,
            "KYC information submitted for review.",
        )

        return redirect(
            "kyc:dashboard"
        )

    return render(
        request,
        "kyc/submit.html",
        {
            "kyc_record": kyc_record,
        },
    )


# ============================================================================
# UPLOAD KYC DOCUMENT
# ============================================================================


@login_required
def upload_document(request):
    vendor = _get_vendor_profile(
        request
    )

    if vendor is None:
        return redirect(
            "vendors:become"
        )

    if request.method == "POST":
        uploaded_file = request.FILES.get(
            "document_file"
        )

        if uploaded_file is None:
            messages.error(
                request,
                "Please select a document to upload.",
            )

            return render(
                request,
                "kyc/upload_form.html",
            )

        document_type = request.POST.get(
            "document_type",
            "",
        ).strip()

        if not document_type:
            messages.error(
                request,
                "Please select a document type.",
            )

            return render(
                request,
                "kyc/upload_form.html",
            )

        document = KYCDocument(
            vendor=vendor,
            document_type=document_type,
            document_file=uploaded_file,
            document_number=request.POST.get(
                "document_number",
                "",
            ).strip(),
            expiry_date=(
                request.POST.get(
                    "expiry_date"
                )
                or None
            ),
            description=request.POST.get(
                "description",
                "",
            ).strip(),
        )

        try:
            # CRITICAL:
            #
            # This runs:
            #
            # document_file.validators
            #     ↓
            # validate_kyc_upload
            #     ↓
            # extension validation
            #     ↓
            # file-size validation
            #     ↓
            # actual signature detection
            #     ↓
            # extension/content matching
            #     ↓
            # Pillow verification for images
            #
            document.full_clean()

            with transaction.atomic():
                document.save()

        except ValidationError as exc:
            logger.warning(
                (
                    "Rejected KYC document upload. "
                    "vendor_id=%s filename=%s errors=%s"
                ),
                vendor.pk,
                getattr(
                    uploaded_file,
                    "name",
                    "",
                ),
                exc.messages,
            )

            errors = _validation_error_messages(
                exc
            )

            for error in errors:
                messages.error(
                    request,
                    error,
                )

            return render(
                request,
                "kyc/upload_form.html",
                {
                    "selected_document_type": (
                        document_type
                    ),
                    "document_number": (
                        document.document_number
                    ),
                    "expiry_date": (
                        request.POST.get(
                            "expiry_date",
                            "",
                        )
                    ),
                    "description": (
                        document.description
                    ),
                },
            )

        except Exception:
            logger.exception(
                (
                    "Unexpected KYC document upload failure. "
                    "vendor_id=%s filename=%s"
                ),
                vendor.pk,
                getattr(
                    uploaded_file,
                    "name",
                    "",
                ),
            )

            messages.error(
                request,
                (
                    "The document could not be uploaded. "
                    "Please try again."
                ),
            )

            return render(
                request,
                "kyc/upload_form.html",
            )

        messages.success(
            request,
            "Document uploaded successfully.",
        )

        return redirect(
            "kyc:dashboard"
        )

    return render(
        request,
        "kyc/upload_form.html",
    )


# ============================================================================
# KYC STATUS
# ============================================================================


@login_required
def kyc_status(request):
    vendor = _get_vendor_profile(
        request
    )

    if vendor is None:
        return redirect(
            "vendors:become"
        )

    try:
        kyc_record = KYCRecord.objects.get(
            vendor=vendor
        )

    except KYCRecord.DoesNotExist:
        messages.info(
            request,
            (
                "You have not submitted your KYC "
                "information yet."
            ),
        )

        return redirect(
            "kyc:dashboard"
        )

    return render(
        request,
        "kyc/status.html",
        {
            "kyc_record": kyc_record,
        },
    )