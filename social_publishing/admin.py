from django.contrib import admin

from .models import SocialAccount, SocialConnectionAuditLog, SocialPublication, TemporaryVideoLease


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "owner_role", "platform", "account_username", "status", "connected_at")
    list_filter = ("owner_role", "platform", "status")
    search_fields = ("user__email", "account_name", "account_username", "external_account_id")
    exclude = ("access_token_encrypted", "refresh_token_encrypted")
    readonly_fields = (
        "external_account_id",
        "account_name",
        "account_username",
        "token_expires_at",
        "scopes",
        "platform_metadata",
        "connected_at",
        "last_verified_at",
        "last_error",
        "created_at",
        "updated_at",
    )


@admin.register(SocialPublication)
class SocialPublicationAdmin(admin.ModelAdmin):
    list_display = ("owner_user", "owner_role", "platform", "status", "source_identity", "attempt_count", "published_at", "archived_at", "created_at")
    list_filter = ("owner_role", "platform", "status", "archived_at")
    search_fields = ("owner_user__email", "external_id", "external_url", "error_code", "original_content_type_label")
    readonly_fields = (
        "owner_user",
        "owner_role",
        "social_account",
        "platform",
        "content_type",
        "object_id",
        "status",
        "external_id",
        "external_url",
        "attempt_count",
        "last_attempt_at",
        "next_retry_at",
        "published_at",
        "error_code",
        "error_message",
        "request_metadata",
        "response_metadata",
        "archived_at",
        "original_content_type_label",
        "original_object_id",
        "archive_metadata",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Original Arolana content")
    def source_identity(self, obj):
        label = obj.original_content_type_label or str(obj.content_type)
        object_id = obj.original_object_id or obj.object_id
        return f"{label} #{object_id}"

    def has_add_permission(self, request):
        return False


@admin.register(SocialConnectionAuditLog)
class SocialConnectionAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "owner_role", "platform", "event", "stage", "http_status")
    list_filter = ("platform", "owner_role", "event")
    search_fields = ("user__email", "external_identity_id", "selected_destination_id", "provider_error_code")
    readonly_fields = tuple(field.name for field in SocialConnectionAuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TemporaryVideoLease)
class TemporaryVideoLeaseAdmin(admin.ModelAdmin):
    list_display = ("owner_user", "owner_role", "original_filename", "file_size", "expires_at", "cleanup_completed_at")
    list_filter = ("owner_role",)
    search_fields = ("owner_user__email", "storage_key", "original_filename")
    readonly_fields = ("created_at", "updated_at")
