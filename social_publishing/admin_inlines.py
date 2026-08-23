from urllib.parse import urlparse

from django.contrib import admin
from django.contrib.contenttypes.admin import GenericStackedInline
from django.utils.html import format_html

from .models import SocialPublication


class SocialPublicationInline(GenericStackedInline):
    """Read-only publication history beside the source video in admin."""

    model = SocialPublication
    ct_field = "content_type"
    ct_fk_field = "object_id"
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name_plural = "External social publication status"
    fieldsets = (
        (
            "Destination request",
            {
                "fields": (
                    ("owner_identity", "destination"),
                    ("status", "attempt_count"),
                    "account_identity",
                )
            },
        ),
        (
            "External result",
            {
                "fields": (
                    "external_id",
                    "instagram_result",
                    "safe_failure",
                )
            },
        ),
        (
            "Timeline",
            {
                "fields": (("last_attempt_at", "published_at", "created_at"),),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = (
        "owner_identity",
        "destination",
        "account_identity",
        "status",
        "attempt_count",
        "external_id",
        "instagram_result",
        "safe_failure",
        "last_attempt_at",
        "published_at",
        "created_at",
    )

    @admin.display(description="Content owner / role")
    def owner_identity(self, obj):
        return f"{obj.owner_user} · {obj.get_owner_role_display()}"

    @admin.display(description="Requested destination")
    def destination(self, obj):
        return obj.get_platform_display()

    @admin.display(description="Connected account")
    def account_identity(self, obj):
        account = obj.social_account
        if not account:
            return "No connected account was available for this attempt"
        return account.account_username or account.account_name or account.external_account_id

    @admin.display(description="Instagram permalink")
    def instagram_result(self, obj):
        value = str(obj.external_url or "").strip()
        try:
            parsed = urlparse(value)
        except ValueError:
            return "—"
        if parsed.scheme != "https" or not (
            parsed.hostname == "instagram.com"
            or str(parsed.hostname or "").endswith(".instagram.com")
        ):
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">View on Instagram</a>', value)

    @admin.display(description="Safe failure")
    def safe_failure(self, obj):
        if not obj.error_code and not obj.error_message:
            return "—"
        return f"{obj.error_code or 'instagram_publish_failed'} · {obj.error_message or 'Publishing failed.'}"

    def has_add_permission(self, request, obj=None):
        return False
