from django.contrib.contenttypes.admin import GenericTabularInline

from .models import SocialPublication


class SocialPublicationInline(GenericTabularInline):
    """Read-only publication history beside the source video in admin."""

    model = SocialPublication
    ct_field = "content_type"
    ct_fk_field = "object_id"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        "owner_user",
        "owner_role",
        "platform",
        "social_account",
        "status",
        "external_id",
        "external_url",
        "attempt_count",
        "error_code",
        "error_message",
        "last_attempt_at",
        "published_at",
        "created_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False
