from django.contrib import admin
from django.utils.html import format_html
from .models import VendorProfile, VendorSubscription

@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'user', 'is_verified', 'rating_avg', 'total_sales', 'logo_preview']
    list_filter = ['is_verified', 'is_active']
    search_fields = ['store_name', 'user__email']
    prepopulated_fields = {'store_slug': ['store_name']}
    readonly_fields = ['rating_avg', 'total_sales', 'followers_count']
    
    def logo_preview(self, obj):
        if obj.store_logo:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.store_logo.url)
        return "No Logo"
    logo_preview.short_description = 'Logo'

@admin.register(VendorSubscription)
class VendorSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'plan', 'start_date', 'end_date', 'is_active']
    list_filter = ['plan', 'is_active']
    search_fields = ['vendor__username']
