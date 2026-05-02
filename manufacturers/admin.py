from django.contrib import admin
from django.utils.html import format_html
from .models import Manufacturer, ManufacturerApplication, ManufacturerCategory, ManufacturerProduct

@admin.register(ManufacturerCategory)
class ManufacturerCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'icon', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    prepopulated_fields = {'slug': ['name']}

@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ['name', 'logo_preview', 'is_featured', 'is_active', 'display_order', 'total_products', 'rating_avg']
    list_editable = ['is_featured', 'is_active', 'display_order']
    list_filter = ['is_featured', 'is_active']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['total_products', 'total_sales', 'rating_avg']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'logo', 'banner', 'description')
        }),
        ('Contact Information', {
            'fields': ('website', 'email', 'phone', 'address'),
            'classes': ('collapse',)
        }),
        ('Social Media', {
            'fields': ('facebook_url', 'twitter_url', 'instagram_url', 'linkedin_url'),
            'classes': ('collapse',)
        }),
        ('Display Settings', {
            'fields': ('is_featured', 'is_active', 'display_order')
        }),
        ('Statistics', {
            'fields': ('total_products', 'total_sales', 'rating_avg'),
            'classes': ('collapse',)
        }),
    )
    
    def logo_preview(self, obj):
        if obj.logo:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 8px; object-fit: cover;" />', obj.logo.url)
        return "-"
    logo_preview.short_description = 'Logo'

@admin.register(ManufacturerApplication)
class ManufacturerApplicationAdmin(admin.ModelAdmin):
    list_display = ['vendor', 'manufacturer', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['vendor__username', 'manufacturer__name']
    actions = ['approve_applications', 'reject_applications']
    
    def approve_applications(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='approved', approved_at=timezone.now())
        self.message_user(request, f"{queryset.count()} applications approved.")
    approve_applications.short_description = "Approve selected applications"
    
    def reject_applications(self, request, queryset):
        queryset.update(status='rejected')
        self.message_user(request, f"{queryset.count()} applications rejected.")
    reject_applications.short_description = "Reject selected applications"

@admin.register(ManufacturerProduct)
class ManufacturerProductAdmin(admin.ModelAdmin):
    list_display = ['manufacturer', 'product', 'vendor', 'is_approved', 'commission_rate']
    list_filter = ['is_approved', 'manufacturer']
    list_editable = ['is_approved', 'commission_rate']
