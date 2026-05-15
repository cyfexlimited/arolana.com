from django.contrib import admin
from django.utils.html import format_html
from .models import (
    HomepageCategory, HomepageBanner, HomepageSection, 
    HomepageVendorSettings, HomepageNewsletterSettings, 
    HomepageBannerImage, HomepageManufacturerSettings, 
    HomepageManufacturerCategory, HomepageVideoSection
)


# 🔥 INLINE IMAGES
class HomepageBannerImageInline(admin.TabularInline):
    model = HomepageBannerImage
    extra = 1
    fields = ['image_preview', 'image', 'position', 'animation', 'display_order', 'is_active']
    readonly_fields = ['image_preview']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="60" style="border-radius:6px;" />',
                obj.image.url
            )
        return "No Image"


# 🔹 CATEGORY ADMIN
@admin.register(HomepageCategory)
class HomepageCategoryAdmin(admin.ModelAdmin):
    list_display = ['category', 'icon_preview', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['category__name']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category')

    def icon_preview(self, obj):
        return format_html('<i class="{} fa-lg"></i>', obj.icon)
    icon_preview.short_description = 'Icon'


# 🔹 BANNER ADMIN
@admin.register(HomepageBanner)
class HomepageBannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'display_order', 'is_active', 'preview']
    list_editable = ['display_order', 'is_active']
    inlines = [HomepageBannerImageInline]

    fieldsets = (
        ('📝 Content', {
            'fields': ('title', 'subtitle', 'button_text', 'button_url')
        }),
        ('🎨 Styling', {
            'fields': ('background_color_start', 'background_color_end')
        }),
        ('🖼 Floating Images', {
            'fields': (
                'left_image', 'right_image', 'center_image',
                'left_animation', 'right_animation', 'center_animation'
            ),
            'classes': ('collapse',)
        }),
        ('⚙️ Settings', {
            'fields': ('display_order', 'is_active')
        }),
    )

    def preview(self, obj):
        img = obj.uploaded_images.filter(is_active=True).first()
        if img and img.image:
            return format_html(
                '<img src="{}" width="70" style="border-radius:6px;" />',
                img.image.url
            )
        return "No Image"
    preview.short_description = "Preview"


# 🔹 SECTIONS
@admin.register(HomepageSection)
class HomepageSectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'section_type', 'products_limit', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['section_type', 'is_active']


# 🔹 VENDOR SETTINGS (SINGLE INSTANCE)
@admin.register(HomepageVendorSettings)
class HomepageVendorSettingsAdmin(admin.ModelAdmin):
    list_display = ['title', 'vendor_count', 'autoplay_speed', 'is_active']

    def has_add_permission(self, request):
        return not HomepageVendorSettings.objects.exists()


# 🔹 NEWSLETTER SETTINGS (SINGLE INSTANCE)
@admin.register(HomepageNewsletterSettings)
class HomepageNewsletterSettingsAdmin(admin.ModelAdmin):
    list_display = ['title', 'button_text', 'is_active']

    def has_add_permission(self, request):
        return not HomepageNewsletterSettings.objects.exists()


# 🔹 BANNER IMAGE ADMIN
@admin.register(HomepageBannerImage)
class HomepageBannerImageAdmin(admin.ModelAdmin):
    list_display = ['banner', 'position', 'image_preview', 'is_active']
    list_filter = ['position', 'is_active']
    readonly_fields = ['image_preview']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="80" style="border-radius:6px;" />',
                obj.image.url
            )
        return "No Image"


# 🔹 MANUFACTURER SETTINGS
@admin.register(HomepageManufacturerSettings)
class HomepageManufacturerSettingsAdmin(admin.ModelAdmin):
    list_display = ['title', 'display_count', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']

    fieldsets = (
        ('📝 Content', {
            'fields': ('title', 'subtitle', 'display_count', 'show_featured_only')
        }),
        ('⚙️ Settings', {
            'fields': ('display_order', 'is_active')
        }),
    )

    def has_add_permission(self, request):
        return not HomepageManufacturerSettings.objects.exists()


# 🔹 MANUFACTURER CATEGORY
@admin.register(HomepageManufacturerCategory)
class HomepageManufacturerCategoryAdmin(admin.ModelAdmin):
    list_display = ['category', 'icon', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['category__name']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category')


# 🔹 VIDEO SECTION (FIXED INDENTATION)
@admin.register(HomepageVideoSection)
class HomepageVideoSectionAdmin(admin.ModelAdmin):
    list_display = ['title', 'video_source', 'info_position', 'position', 'display_order', 'is_active', 'status']
    list_editable = ['info_position', 'position', 'display_order', 'is_active']
    list_filter = ['video_source', 'info_position', 'position', 'is_active']

    fieldsets = (
        ('📝 Content', {
            'fields': ('title', 'subtitle')
        }),
        ('🎥 Source', {
            'fields': ('video_source',)
        }),
        ('📺 YouTube', {
            'fields': ('youtube_url',),
            'classes': ('collapse',)
        }),
        ('🎬 Vimeo', {
            'fields': ('vimeo_url',),
            'classes': ('collapse',)
        }),
        ('💾 Local Video', {
            'fields': ('local_video', 'poster_image'),
        }),
        ('📐 Layout', {
            'fields': ('info_position', 'position', 'video_width', 'video_height', 'background_color', 'text_color'),
            'description': 'Info position controls where title, subtitle, and CTA appear relative to the video. Position aligns the whole block inside the section.'
        }),
        ('⚙️ Behavior', {
            'fields': ('autoplay', 'loop', 'show_controls')
        }),
        ('🔘 CTA', {
            'fields': ('button_text', 'button_url', 'button_color'),
            'classes': ('collapse',)
        }),
        ('📊 Settings', {
            'fields': ('display_order', 'is_active')
        }),
    )

    def status(self, obj):
        if obj.video_source == 'youtube' and obj.youtube_id:
            return format_html('<span style="color:green;">{}</span>', 'YouTube Ready')
        elif obj.video_source == 'local' and obj.local_video:
            return format_html('<span style="color:blue;">{}</span>', 'Local Ready')
        elif obj.video_source == 'vimeo' and obj.vimeo_id:
            return format_html('<span style="color:purple;">{}</span>', 'Vimeo Ready')
        return format_html('<span style="color:orange;">{}</span>', 'Not Configured')
    status.short_description = "Status"
