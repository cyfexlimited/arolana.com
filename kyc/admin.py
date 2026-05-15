from django.contrib import admin
from django.utils import timezone

from .models import KYCRecord, KYCDocument


@admin.register(KYCRecord)
class KYCRecordAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'kyc_status', 'risk_level', 'reviewed_by', 'submitted_at', 'reviewed_at']
    list_filter = ['kyc_status', 'risk_level', 'submitted_at', 'reviewed_at']
    search_fields = ['vendor__store_name', 'vendor__user__email', 'legal_business_name', 'business_email']
    readonly_fields = ['created_at', 'updated_at', 'submitted_at', 'reviewed_at']
    actions = ['approve_kyc', 'reject_kyc', 'mark_in_review']

    fieldsets = (
        ('Vendor', {'fields': ('vendor', 'kyc_status')}),
        ('Business Information', {
            'fields': ('legal_business_name', 'registration_number', 'tax_id', 'vat_number', 'business_type')
        }),
        ('Address', {
            'fields': ('business_address', 'city', 'state', 'country', 'postal_code')
        }),
        ('Contact', {
            'fields': ('business_phone', 'business_email', 'website')
        }),
        ('Authorized Person', {
            'fields': ('authorized_person_name', 'authorized_person_title', 'authorized_person_email', 'authorized_person_phone')
        }),
        ('Review', {
            'fields': ('risk_score', 'risk_level', 'reviewed_by', 'reviewed_at', 'review_notes', 'rejection_reason')
        }),
        ('Compliance', {
            'fields': ('pep_check', 'sanctions_check', 'adverse_media_check'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('submitted_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if obj.kyc_status in ['verified', 'rejected', 'suspended']:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
        self._sync_vendor_verification(obj)

    def _sync_vendor_verification(self, obj):
        obj.vendor.is_verified = obj.kyc_status == 'verified'
        obj.vendor.save(update_fields=['is_verified', 'updated_at'])

    def approve_kyc(self, request, queryset):
        for record in queryset:
            record.kyc_status = 'verified'
            record.reviewed_by = request.user
            record.reviewed_at = timezone.now()
            record.save()
            self._sync_vendor_verification(record)
        self.message_user(request, f'{queryset.count()} KYC record(s) approved.')
    approve_kyc.short_description = 'Approve selected KYC records'

    def reject_kyc(self, request, queryset):
        for record in queryset:
            record.kyc_status = 'rejected'
            record.reviewed_by = request.user
            record.reviewed_at = timezone.now()
            record.save()
            self._sync_vendor_verification(record)
        self.message_user(request, f'{queryset.count()} KYC record(s) rejected.')
    reject_kyc.short_description = 'Reject selected KYC records'

    def mark_in_review(self, request, queryset):
        queryset.update(kyc_status='in_review')
        self.message_user(request, f'{queryset.count()} KYC record(s) moved to review.')
    mark_in_review.short_description = 'Mark selected KYC records in review'


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'document_type', 'verification_status', 'verified_by', 'uploaded_at', 'verified_at']
    list_filter = ['document_type', 'verification_status', 'uploaded_at']
    search_fields = ['vendor__store_name', 'vendor__user__email', 'document_number']
    readonly_fields = ['uploaded_at', 'verified_at']
    actions = ['verify_documents', 'reject_documents']

    def verify_documents(self, request, queryset):
        queryset.update(verification_status='verified', verified_by=request.user, verified_at=timezone.now())
        self.message_user(request, f'{queryset.count()} document(s) verified.')
    verify_documents.short_description = 'Verify selected documents'

    def reject_documents(self, request, queryset):
        queryset.update(verification_status='rejected', verified_by=request.user, verified_at=timezone.now())
        self.message_user(request, f'{queryset.count()} document(s) rejected.')
    reject_documents.short_description = 'Reject selected documents'
