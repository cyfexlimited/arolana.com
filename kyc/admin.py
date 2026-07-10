from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from .models import KYCRecord, KYCDocument


# ============================================================================
# KYC RECORD ADMIN
# ============================================================================


@admin.register(KYCRecord)
class KYCRecordAdmin(admin.ModelAdmin):
    list_display = (
        "vendor",
        "kyc_status",
        "risk_level",
        "reviewed_by",
        "submitted_at",
        "reviewed_at",
    )

    list_filter = (
        "kyc_status",
        "risk_level",
        "submitted_at",
        "reviewed_at",
    )

    search_fields = (
        "vendor__store_name",
        "vendor__user__email",
        "legal_business_name",
        "business_email",
        "registration_number",
        "tax_id",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "submitted_at",
        "reviewed_at",
    )

    actions = (
        "approve_kyc",
        "reject_kyc",
        "mark_in_review",
    )

    list_select_related = (
        "vendor",
        "vendor__user",
        "reviewed_by",
    )

    list_per_page = 100

    ordering = (
        "-created_at",
    )

    fieldsets = (
        (
            "Vendor",
            {
                "fields": (
                    "vendor",
                    "kyc_status",
                ),
            },
        ),
        (
            "Business Information",
            {
                "fields": (
                    "legal_business_name",
                    "registration_number",
                    "tax_id",
                    "vat_number",
                    "business_type",
                    "year_established",
                    "number_of_employees",
                    "estimated_annual_revenue",
                ),
            },
        ),
        (
            "Business Address",
            {
                "fields": (
                    "business_address",
                    "city",
                    "state",
                    "country",
                    "postal_code",
                ),
            },
        ),
        (
            "Business Contact",
            {
                "fields": (
                    "business_phone",
                    "business_email",
                    "website",
                ),
            },
        ),
        (
            "Bank Account",
            {
                "fields": (
                    "bank_name",
                    "bank_account_name",
                    "bank_account_number",
                    "bank_routing_number",
                    "iban",
                    "swift_code",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Manufacturer & International Trade",
            {
                "fields": (
                    "factory_address",
                    "warehouse_address",
                    "manufacturer_certificate_number",
                    "import_export_license_number",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Authorized Person",
            {
                "fields": (
                    "authorized_person_name",
                    "authorized_person_title",
                    "authorized_person_email",
                    "authorized_person_phone",
                ),
            },
        ),
        (
            "Risk Assessment",
            {
                "fields": (
                    "risk_score",
                    "risk_level",
                ),
            },
        ),
        (
            "Review",
            {
                "fields": (
                    "reviewed_by",
                    "reviewed_at",
                    "review_notes",
                    "rejection_reason",
                ),
            },
        ),
        (
            "Compliance",
            {
                "fields": (
                    "pep_check",
                    "sanctions_check",
                    "adverse_media_check",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "submitted_at",
                    "created_at",
                    "updated_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):
        """
        Keep review metadata and vendor verification state synchronized
        whenever a KYC record is edited in Django Admin.
        """

        reviewed_statuses = {
            "verified",
            "approved",
            "rejected",
            "suspended",
        }

        if obj.kyc_status in reviewed_statuses:
            obj.reviewed_by = request.user

            if not obj.reviewed_at:
                obj.reviewed_at = timezone.now()

        super().save_model(
            request,
            obj,
            form,
            change,
        )

        self._sync_vendor_verification(
            obj
        )

    def _sync_vendor_verification(
        self,
        record,
    ):
        """
        Vendor is verified only when the KYC record has reached an
        approved/verified state.
        """

        should_be_verified = (
            record.kyc_status
            in {
                "verified",
                "approved",
            }
        )

        vendor = record.vendor

        if vendor.is_verified != should_be_verified:
            vendor.is_verified = should_be_verified

            vendor.save(
                update_fields=[
                    "is_verified",
                    "updated_at",
                ]
            )

    @admin.action(
        description="Approve selected KYC records"
    )
    def approve_kyc(
        self,
        request,
        queryset,
    ):
        now = timezone.now()

        updated_count = 0

        with transaction.atomic():
            for record in queryset.select_related(
                "vendor"
            ):
                record.kyc_status = "verified"
                record.reviewed_by = request.user
                record.reviewed_at = now

                record.save(
                    update_fields=[
                        "kyc_status",
                        "reviewed_by",
                        "reviewed_at",
                        "updated_at",
                    ]
                )

                self._sync_vendor_verification(
                    record
                )

                updated_count += 1

        self.message_user(
            request,
            (
                f"{updated_count} KYC record(s) approved "
                "and vendor verification synchronized."
            ),
            level=messages.SUCCESS,
        )

    @admin.action(
        description="Reject selected KYC records"
    )
    def reject_kyc(
        self,
        request,
        queryset,
    ):
        now = timezone.now()

        updated_count = 0

        with transaction.atomic():
            for record in queryset.select_related(
                "vendor"
            ):
                record.kyc_status = "rejected"
                record.reviewed_by = request.user
                record.reviewed_at = now

                record.save(
                    update_fields=[
                        "kyc_status",
                        "reviewed_by",
                        "reviewed_at",
                        "updated_at",
                    ]
                )

                self._sync_vendor_verification(
                    record
                )

                updated_count += 1

        self.message_user(
            request,
            (
                f"{updated_count} KYC record(s) rejected "
                "and vendor verification synchronized."
            ),
            level=messages.WARNING,
        )

    @admin.action(
        description="Mark selected KYC records as in review"
    )
    def mark_in_review(
        self,
        request,
        queryset,
    ):
        updated_count = queryset.update(
            kyc_status="in_review"
        )

        self.message_user(
            request,
            (
                f"{updated_count} KYC record(s) "
                "moved to review."
            ),
            level=messages.INFO,
        )


# ============================================================================
# KYC DOCUMENT ADMIN
# ============================================================================


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "vendor",
        "document_type",
        "verification_status",
        "verified_by",
        "uploaded_at",
        "verified_at",
    )

    list_filter = (
        "document_type",
        "verification_status",
        "uploaded_at",
        "verified_at",
    )

    search_fields = (
        "vendor__store_name",
        "vendor__user__email",
        "document_number",
    )

    readonly_fields = (
        "uploaded_at",
        "verified_at",
    )

    actions = (
        "verify_documents",
        "reject_documents",
        "mark_documents_pending",
    )

    list_select_related = (
        "vendor",
        "vendor__user",
        "verified_by",
    )

    list_per_page = 100

    ordering = (
        "-uploaded_at",
    )

    fieldsets = (
        (
            "Vendor",
            {
                "fields": (
                    "vendor",
                ),
            },
        ),
        (
            "Document",
            {
                "fields": (
                    "document_type",
                    "document_file",
                    "document_number",
                    "expiry_date",
                    "description",
                ),
            },
        ),
        (
            "Verification",
            {
                "fields": (
                    "verification_status",
                    "verified_by",
                    "verified_at",
                    "rejection_reason",
                ),
            },
        ),
        (
            "Upload Information",
            {
                "fields": (
                    "uploaded_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    def save_model(
        self,
        request,
        obj,
        form,
        change,
    ):
        """
        The document_file model-field validator runs through the
        admin ModelForm before this method is reached.

        This method only manages verification metadata.
        """

        reviewed_statuses = {
            "verified",
            "rejected",
            "expired",
        }

        if obj.verification_status in reviewed_statuses:
            obj.verified_by = request.user

            if not obj.verified_at:
                obj.verified_at = timezone.now()

        elif obj.verification_status == "pending":
            obj.verified_by = None
            obj.verified_at = None

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    @admin.action(
        description="Verify selected documents"
    )
    def verify_documents(
        self,
        request,
        queryset,
    ):
        now = timezone.now()

        updated_count = queryset.update(
            verification_status="verified",
            verified_by=request.user,
            verified_at=now,
            rejection_reason="",
        )

        self.message_user(
            request,
            (
                f"{updated_count} document(s) verified."
            ),
            level=messages.SUCCESS,
        )

    @admin.action(
        description="Reject selected documents"
    )
    def reject_documents(
        self,
        request,
        queryset,
    ):
        now = timezone.now()

        updated_count = queryset.update(
            verification_status="rejected",
            verified_by=request.user,
            verified_at=now,
        )

        self.message_user(
            request,
            (
                f"{updated_count} document(s) rejected."
            ),
            level=messages.WARNING,
        )

    @admin.action(
        description="Return selected documents to pending review"
    )
    def mark_documents_pending(
        self,
        request,
        queryset,
    ):
        updated_count = queryset.update(
            verification_status="pending",
            verified_by=None,
            verified_at=None,
            rejection_reason="",
        )

        self.message_user(
            request,
            (
                f"{updated_count} document(s) "
                "returned to pending review."
            ),
            level=messages.INFO,
        )