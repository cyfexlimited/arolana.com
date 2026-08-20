from django.contrib import admin

from .models import SocialAccount, SocialPublication, TemporaryVideoLease


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "owner_role", "platform", "account_username", "status", "connected_at")
    list_filter = ("owner_role", "platform", "status")
    search_fields = ("user__email", "account_name", "account_username", "external_account_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SocialPublication)
class SocialPublicationAdmin(admin.ModelAdmin):
    list_display = ("owner_user", "owner_role", "platform", "status", "attempt_count", "published_at", "created_at")
    list_filter = ("owner_role", "platform", "status")
    search_fields = ("owner_user__email", "external_id", "external_url", "error_code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TemporaryVideoLease)
class TemporaryVideoLeaseAdmin(admin.ModelAdmin):
    list_display = ("owner_user", "owner_role", "original_filename", "file_size", "expires_at", "cleanup_completed_at")
    list_filter = ("owner_role",)
    search_fields = ("owner_user__email", "storage_key", "original_filename")
    readonly_fields = ("created_at", "updated_at")
