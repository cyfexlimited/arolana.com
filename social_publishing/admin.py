from django.contrib import admin

from .models import SocialAccount, SocialPublication, TemporaryVideoLease


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
    list_display = ("owner_user", "owner_role", "platform", "status", "attempt_count", "published_at", "created_at")
    list_filter = ("owner_role", "platform", "status")
    search_fields = ("owner_user__email", "external_id", "external_url", "error_code")
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
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(TemporaryVideoLease)
class TemporaryVideoLeaseAdmin(admin.ModelAdmin):
    list_display = ("owner_user", "owner_role", "original_filename", "file_size", "expires_at", "cleanup_completed_at")
    list_filter = ("owner_role",)
    search_fields = ("owner_user__email", "storage_key", "original_filename")
    readonly_fields = ("created_at", "updated_at")
