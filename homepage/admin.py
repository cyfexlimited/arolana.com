from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import (
    HomepageCategory, HomepageBanner, HomepageSection, 
    HomepageVendorSettings, HomepageNewsletterSettings, 
    HomepageBannerImage, HomepageManufacturerSettings, 
    HomepageManufacturerCategory, HomepageVideoSection
)

class HomepageBannerImageInline(admin.TabularInline):
    model = HomepageBannerImage
    extra = 1
    fields = ['image', 'position', 'animation', 'display_order', 'is_active']

@admin.register(HomepageCategory)
class HomepageCategoryAdmin(admin.ModelAdmin):
    list_display = ['category', 'icon', 'display_order', 'is_active', 'icon_preview']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['category__name']
    
    def icon_preview(self, obj):
        return format_html('<i class="{} fa-2x"></i>', obj.icon)
    icon_preview.short_description = 'Icon'

@admin.register(HomepageBanner)
class HomepageBannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'button_text', 'display_order', 'is_active', 'image_preview']
    list_editable = ['display_order', 'is_active']
    inlines = [HomepageBannerImageInline]
    
    fieldsets = (
        ('Content', {
            'fields': ('title', 'subtitle', 'button_text', 'button_url')
        }),
        ('Styling', {
            'fields': ('background_color_start', 'background_color_end')
        }),
        ('Floating Images', {
            'fields': ('left_image', 'right_image', 'center_image', 
                      'left_animation', 'right_animation', 'center_animation'),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': ('display_order', 'is_active')
        }),
    )
    
    def image_preview(self, obj):
        images = obj.uploaded_images.filter(is_active=True)
        if images.exists():
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 4px;" />', images.first().image.url)
        return "No Image"
    image_preview.short_description = 'Preview'

@admin.register(HomepageSection)
class HomepageSectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'section_type', 'products_limit', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['section_type', 'is_active']

@admin.register(HomepageVendorSettings)
class HomepageVendorSettingsAdmin(admin.ModelAdmin):
    list_display = ['title', 'vendor_count', 'autoplay_speed', 'is_active']
    
    def has_add_permission(self, request):
        return not HomepageVendorSettings.objects.exists()

@admin.register(HomepageNewsletterSettings)
class HomepageNewsletterSettingsAdmin(admin.ModelAdmin):
    list_display = ['title', 'button_text', 'is_active']
    
    def has_add_permission(self, request):
        return not HomepageNewsletterSettings.objects.exists()

@admin.register(HomepageBannerImage)
class HomepageBannerImageAdmin(admin.ModelAdmin):
    list_display = ['banner', 'position', 'image_preview', 'is_active']
    list_filter = ['position', 'is_active']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="80" height="80" style="object-fit: cover; border-radius: 4px;" />', obj.image.url)
        return "No Image"
    image_preview.short_description = 'Preview'

@admin.register(HomepageManufacturerSettings)
class HomepageManufacturerSettingsAdmin(admin.ModelAdmin):
    list_display = ['title', 'display_count', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    fieldsets = (
        ('Section Content', {
            'fields': ('title', 'subtitle', 'display_count', 'show_featured_only')
        }),
        ('Display Settings', {
            'fields': ('display_order', 'is_active')
        }),
    )
    
    def has_add_permission(self, request):
        return not HomepageManufacturerSettings.objects.exists()

@admin.register(HomepageManufacturerCategory)
class HomepageManufacturerCategoryAdmin(admin.ModelAdmin):
    list_display = ['category', 'icon', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['category__name']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category')

@admin.register(HomepageVideoSection)
class HomepageVideoSectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'video_source', 'position', 'display_order', 'is_active', 'video_status']
    list_editable = ['position', 'display_order', 'is_active']
    list_filter = ['video_source', 'position', 'is_active']
    
    fieldsets = (
        ('Content', {
            'fields': ('title', 'subtitle')
        }),
        ('Video Source', {
            'fields': ('video_source',),
            'description': 'Choose where your video comes from'
        }),
        ('YouTube Settings (for online videos)', {
            'fields': ('youtube_url',),
            'classes': ('collapse',),
            'description': 'Enter YouTube URL - requires internet connection'
        }),
        ('Local Video Settings (works offline!)', {
            'fields': ('local_video', 'poster_image'),
            'classes': ('wide',),
            'description': 'Upload MP4 file for offline playback. Recommended size: 1920x1080'
        }),
        ('Position & Layout', {
            'fields': ('position', 'video_width', 'video_height', 'background_color', 'text_color')
        }),
        ('Video Settings', {
            'fields': ('autoplay', 'loop', 'show_controls'),
            'description': 'Note: Autoplay may be blocked by some browsers'
        }),
        ('Call to Action', {
            'fields': ('button_text', 'button_url', 'button_color'),
            'classes': ('collapse',)
        }),
        ('Display Settings', {
            'fields': ('display_order', 'is_active')
        }),
    )
    
    def video_status(self, obj):
        if obj.video_source == 'youtube' and obj.youtube_id:
            return format_html('<span style="color: green;"><i class="fas fa-youtube"></i> YouTube Ready</span>')
        elif obj.video_source == 'local' and obj.local_video:
            return format_html('<span style="color: blue;"><i class="fas fa-video"></i> Local Video Ready</span>')
        else:
            return format_html('<span style="color: orange;"><i class="fas fa-exclamation-triangle"></i> Not Configured</span>')
    video_status.short_description = 'Status'
    
    def save_model(self, request, obj, form, change):
        # Auto-extract YouTube ID when URL is provided
        if obj.youtube_url and 'youtube.com' in obj.youtube_url:
            if 'v=' in obj.youtube_url:
                obj.youtube_id = obj.youtube_url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in obj.youtube_url:
                obj.youtube_id = obj.youtube_url.split('youtu.be/')[1].split('?')[0]
            else:
                obj.youtube_id = None
        elif obj.youtube_url and 'youtu.be' in obj.youtube_url:
            obj.youtube_id = obj.youtube_url.split('youtu.be/')[1].split('?')[0]
        else:
            obj.youtube_id = None
            
        super().save_model(request, obj, form, change)