from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import NewsletterSubscriber, NewsletterCampaign, NewsletterTracking

@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ['email', 'name', 'source', 'is_active', 'subscribed_at']
    list_filter = ['is_active', 'source', 'subscribed_at']
    search_fields = ['email', 'name']
    actions = ['activate_subscribers', 'deactivate_subscribers', 'export_subscribers']
    
    def activate_subscribers(self, request, queryset):
        queryset.update(is_active=True, unsubscribed_at=None)
        self.message_user(request, f"{queryset.count()} subscribers activated.")
    activate_subscribers.short_description = "Activate selected subscribers"
    
    def deactivate_subscribers(self, request, queryset):
        from django.utils import timezone
        queryset.update(is_active=False, unsubscribed_at=timezone.now())
        self.message_user(request, f"{queryset.count()} subscribers deactivated.")
    deactivate_subscribers.short_description = "Deactivate selected subscribers"
    
    def export_subscribers(self, request, queryset):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="subscribers.csv"'
        writer = csv.writer(response)
        writer.writerow(['Email', 'Name', 'Source', 'Subscribed At', 'Status'])
        for sub in queryset:
            writer.writerow([sub.email, sub.name, sub.source, sub.subscribed_at, 'Active' if sub.is_active else 'Inactive'])
        return response
    export_subscribers.short_description = "Export selected subscribers"

@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'subject', 'status', 'sent_count', 'open_count', 'click_count', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'subject']
    readonly_fields = ['sent_count', 'open_count', 'click_count', 'sent_at']
    actions = ['duplicate_campaign']
    
    fieldsets = (
        ('Campaign Information', {
            'fields': ('name', 'subject', 'status')
        }),
        ('Content', {
            'fields': ('content', 'html_content'),
            'classes': ('wide',)
        }),
        ('Schedule', {
            'fields': ('scheduled_at',),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('sent_count', 'open_count', 'click_count', 'sent_at'),
            'classes': ('collapse',)
        }),
    )
    
    def duplicate_campaign(self, request, queryset):
        for campaign in queryset:
            campaign.pk = None
            campaign.name = f"{campaign.name} (Copy)"
            campaign.status = 'draft'
            campaign.sent_count = 0
            campaign.open_count = 0
            campaign.click_count = 0
            campaign.sent_at = None
            campaign.save()
        self.message_user(request, f"{queryset.count()} campaign(s) duplicated.")
    duplicate_campaign.short_description = "Duplicate selected campaigns"

@admin.register(NewsletterTracking)
class NewsletterTrackingAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'subscriber', 'opened_at', 'clicked_at']
    list_filter = ['opened_at', 'clicked_at']
    search_fields = ['campaign__name', 'subscriber__email']
    readonly_fields = ['campaign', 'subscriber', 'opened_at', 'clicked_at', 'ip_address', 'user_agent']
    
    def has_add_permission(self, request):
        return False
