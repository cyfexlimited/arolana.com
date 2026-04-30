from django.contrib import admin
from django.utils.html import format_html
from .models import Video, VideoGallery, VideoAnalytics

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ['title', 'video_type', 'thumbnail_preview', 'views', 'is_featured', 'is_active']
    list_filter = ['video_type', 'is_featured', 'is_active']
    search_fields = ['title', 'description']
    list_editable = ['is_featured', 'is_active']
    readonly_fields = ['views', 'likes', 'auto_thumbnail']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'video_type')
        }),
        ('Video Source', {
            'fields': ('youtube_id', 'vimeo_id', 'video_file', 'embed_code', 'streaming_url'),
            'description': 'Fill in the appropriate field based on video type'
        }),
        ('Thumbnail', {
            'fields': ('custom_thumbnail', 'auto_thumbnail'),
            'description': 'Upload custom thumbnail or it will be auto-fetched'
        }),
        ('Player Settings', {
            'fields': ('autoplay', 'loop', 'muted', 'controls', 'start_time', 'end_time', 'preferred_quality')
        }),
        ('Display', {
            'fields': ('display_order', 'is_featured', 'is_active')
        }),
        ('Statistics', {
            'fields': ('views', 'likes'),
            'classes': ('collapse',)
        }),
    )
    
    def thumbnail_preview(self, obj):
        if obj.custom_thumbnail:
            return format_html('<img src="{}" width="100" height="56" style="border-radius: 4px;" />', obj.custom_thumbnail.url)
        elif obj.auto_thumbnail:
            return format_html('<img src="{}" width="100" height="56" style="border-radius: 4px;" />', obj.auto_thumbnail)
        return "No thumbnail"
    thumbnail_preview.short_description = 'Preview'

@admin.register(VideoGallery)
class VideoGalleryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'video_count', 'is_active']
    prepopulated_fields = {'slug': ['name']}
    filter_horizontal = ['videos']
    
    def video_count(self, obj):
        return obj.videos.count()
    video_count.short_description = 'Videos'

@admin.register(VideoAnalytics)
class VideoAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['video', 'action', 'watch_time', 'timestamp']
    list_filter = ['action', 'timestamp']
    readonly_fields = ['video', 'session_id', 'user', 'action', 'watch_time', 'timestamp', 'ip_address']
    
    def has_add_permission(self, request):
        return False
