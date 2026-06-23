import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html

from .emailing import (
    campaign_recipient_emails,
    render_campaign_html,
    send_campaign,
    send_test_campaign,
    sync_email_audience,
)
from .models import (
    EmailAudienceMember,
    NewsletterCampaign,
    NewsletterSubscriber,
    NewsletterTracking,
)


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = [
        "email",
        "name",
        "source",
        "is_active",
        "subscribed_at",
    ]

    list_filter = [
        "is_active",
        "source",
        "subscribed_at",
    ]

    search_fields = [
        "email",
        "name",
    ]

    list_editable = [
        "is_active",
    ]

    actions = [
        "activate_subscribers",
        "deactivate_subscribers",
        "export_subscribers",
    ]

    def activate_subscribers(self, request, queryset):
        updated = queryset.update(is_active=True, unsubscribed_at=None)
        self.message_user(request, f"{updated} subscribers activated.")

    activate_subscribers.short_description = "Activate selected subscribers"

    def deactivate_subscribers(self, request, queryset):
        from django.utils import timezone

        updated = queryset.update(is_active=False, unsubscribed_at=timezone.now())
        self.message_user(request, f"{updated} subscribers deactivated.")

    deactivate_subscribers.short_description = "Deactivate selected subscribers"

    def export_subscribers(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="subscribers.csv"'

        writer = csv.writer(response)
        writer.writerow(["Email", "Name", "Source", "Subscribed At", "Status"])

        for sub in queryset:
            writer.writerow([
                sub.email,
                sub.name,
                sub.source,
                sub.subscribed_at,
                "Active" if sub.is_active else "Inactive",
            ])

        return response

    export_subscribers.short_description = "Export selected subscribers"


@admin.register(EmailAudienceMember)
class EmailAudienceMemberAdmin(admin.ModelAdmin):
    list_display = [
        "email",
        "name",
        "source",
        "is_active",
        "accepts_promos",
        "last_synced_at",
    ]

    list_filter = [
        "source",
        "is_active",
        "accepts_promos",
        "last_synced_at",
    ]

    search_fields = [
        "email",
        "name",
        "user__email",
        "subscriber__email",
    ]

    list_editable = [
        "is_active",
        "accepts_promos",
    ]

    actions = [
        "sync_all_emails",
        "activate_members",
        "deactivate_members",
        "export_members",
    ]

    def sync_all_emails(self, request, queryset):
        count = sync_email_audience()
        self.message_user(
            request,
            f"Synced {count} registered/newsletter email record(s) into the email audience box.",
        )

    sync_all_emails.short_description = "Sync registered users and newsletter subscribers"

    def activate_members(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} email audience member(s) activated.")

    activate_members.short_description = "Activate selected emails"

    def deactivate_members(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} email audience member(s) deactivated.")

    deactivate_members.short_description = "Deactivate selected emails"

    def export_members(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="email_audience.csv"'

        writer = csv.writer(response)
        writer.writerow(["Email", "Name", "Source", "Active", "Accepts Promos"])

        for member in queryset:
            writer.writerow([
                member.email,
                member.name,
                member.get_source_display(),
                member.is_active,
                member.accepts_promos,
            ])

        return response

    export_members.short_description = "Export selected email audience"


@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "campaign_type",
        "subject",
        "recipient_scope",
        "status",
        "estimated_recipients",
        "sent_count",
        "failed_count",
        "last_sent_at",
        "created_at",
    ]

    list_filter = [
        "status",
        "campaign_type",
        "recipient_scope",
        "send_frequency",
        "created_at",
    ]

    search_fields = [
        "name",
        "subject",
        "headline",
        "product_title",
    ]

    readonly_fields = [
        "hero_image_preview",
        "product_image_preview",
        "email_preview",
        "estimated_recipients",
        "sent_count",
        "failed_count",
        "open_count",
        "click_count",
        "sent_at",
        "last_sent_at",
    ]

    actions = [
        "send_test_selected_campaigns",
        "send_selected_campaigns",
        "duplicate_campaign",
        "mark_as_draft",
        "cancel_campaigns",
    ]

    autocomplete_fields = [
        "related_product",
    ]

    fieldsets = (
        ("Campaign Information", {
            "fields": (
                "name",
                "campaign_type",
                "subject",
                "preheader",
                "status",
                "recipient_scope",
                "send_frequency",
                "test_email",
            )
        }),
        ("Designed Email Header", {
            "fields": (
                "eyebrow",
                "headline",
                "subheadline",
                "hero_image",
                "hero_image_url",
                "hero_image_preview",
            )
        }),
        ("Product / Offer Section", {
            "fields": (
                "related_product",
                "product_title",
                "product_price_text",
                "product_description",
                "product_image",
                "product_image_url",
                "product_image_preview",
            )
        }),
        ("Email Body", {
            "fields": (
                "content",
                "html_content",
            ),
            "classes": ("wide",),
        }),
        ("Buttons / CTA", {
            "fields": (
                "button_text",
                "button_url",
                "secondary_button_text",
                "secondary_button_url",
            )
        }),
        ("Footer", {
            "fields": (
                "footer_note",
            )
        }),
        ("Schedule", {
            "fields": (
                "scheduled_at",
                "last_sent_at",
            ),
            "classes": ("collapse",),
        }),
        ("Statistics", {
            "fields": (
                "estimated_recipients",
                "sent_count",
                "failed_count",
                "open_count",
                "click_count",
                "sent_at",
            ),
            "classes": ("collapse",),
        }),
        ("Live Email Preview", {
            "fields": (
                "email_preview",
            ),
            "classes": ("collapse",),
        }),
    )

    def hero_image_preview(self, obj):
        if not obj:
            return "Save campaign first."

        image_url = ""
        try:
            if obj.hero_image and obj.hero_image.url:
                image_url = obj.hero_image.url
        except Exception:
            image_url = ""

        if not image_url:
            image_url = obj.hero_image_url

        if image_url:
            return format_html(
                '<img src="{}" style="max-width:420px;width:100%;height:auto;border-radius:16px;border:1px solid #e5e7eb;" />',
                image_url,
            )

        return "No hero image."

    hero_image_preview.short_description = "Hero image preview"

    def product_image_preview(self, obj):
        if not obj:
            return "Save campaign first."

        image_url = ""
        try:
            if obj.product_image and obj.product_image.url:
                image_url = obj.product_image.url
        except Exception:
            image_url = ""

        if not image_url:
            image_url = obj.product_image_url

        if image_url:
            return format_html(
                '<img src="{}" style="max-width:220px;width:100%;height:auto;border-radius:16px;border:1px solid #e5e7eb;" />',
                image_url,
            )

        return "No product image."

    product_image_preview.short_description = "Product image preview"

    def email_preview(self, obj):
        if not obj:
            return "Save campaign first."

        html = render_campaign_html(
            obj,
            recipient_email="preview@arolana.com",
            tracking=None,
            is_test=True,
        )

        return format_html(
            '<iframe style="width:100%;height:720px;border:1px solid #d1d5db;border-radius:16px;background:white;" srcdoc="{}"></iframe>',
            html.replace('"', "&quot;"),
        )

    email_preview.short_description = "Email preview"

    def estimated_recipients(self, obj):
        if not obj or not obj.pk:
            return 0

        try:
            return len(campaign_recipient_emails(obj))
        except Exception:
            return "Sync needed"

    estimated_recipients.short_description = "Estimated recipients"

    def duplicate_campaign(self, request, queryset):
        count = 0

        for campaign in queryset:
            campaign.pk = None
            campaign.name = f"{campaign.name} (Copy)"
            campaign.status = "draft"
            campaign.sent_count = 0
            campaign.failed_count = 0
            campaign.open_count = 0
            campaign.click_count = 0
            campaign.sent_at = None
            campaign.last_sent_at = None
            campaign.save()
            count += 1

        self.message_user(request, f"{count} campaign(s) duplicated.")

    duplicate_campaign.short_description = "Duplicate selected campaigns"

    def send_test_selected_campaigns(self, request, queryset):
        total = 0
        skipped = 0

        for campaign in queryset:
            if campaign.test_email:
                total += send_test_campaign(campaign)
            else:
                skipped += 1

        if total:
            self.message_user(request, f"Sent {total} test campaign email(s).")

        if skipped:
            self.message_user(
                request,
                f"{skipped} campaign(s) skipped because test email is empty.",
                level="warning",
            )

    send_test_selected_campaigns.short_description = "Send test email for selected campaigns"

    def send_selected_campaigns(self, request, queryset):
        total = 0

        for campaign in queryset:
            total += send_campaign(campaign)

        self.message_user(request, f"Sent {total} campaign email(s).")

    send_selected_campaigns.short_description = "Send selected campaigns now"

    def mark_as_draft(self, request, queryset):
        updated = queryset.update(status="draft")
        self.message_user(request, f"{updated} campaign(s) marked as draft.")

    mark_as_draft.short_description = "Mark selected campaigns as draft"

    def cancel_campaigns(self, request, queryset):
        updated = queryset.update(status="cancelled")
        self.message_user(request, f"{updated} campaign(s) cancelled.")

    cancel_campaigns.short_description = "Cancel selected campaigns"


@admin.register(NewsletterTracking)
class NewsletterTrackingAdmin(admin.ModelAdmin):
    list_display = [
        "campaign",
        "subscriber",
        "opened_at",
        "clicked_at",
    ]

    list_filter = [
        "opened_at",
        "clicked_at",
    ]

    search_fields = [
        "campaign__name",
        "subscriber__email",
    ]

    readonly_fields = [
        "campaign",
        "subscriber",
        "opened_at",
        "clicked_at",
        "ip_address",
        "user_agent",
    ]

    def has_add_permission(self, request):
        return False