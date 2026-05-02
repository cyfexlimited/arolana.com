from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import BlogCategory, BlogTag, BlogPost, BlogComment, NewsletterSubscriber

@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'color_preview', 'is_active', 'post_count']
    prepopulated_fields = {'slug': ['name']}
    list_editable = ['is_active']
    search_fields = ['name']
    
    def color_preview(self, obj):
        return format_html('<div style="width: 30px; height: 30px; background: {}; border-radius: 50%; border: 1px solid #ddd;"></div>', obj.color)
    color_preview.short_description = 'Color'
    
    def post_count(self, obj):
        return obj.posts.filter(is_published=True).count()
    post_count.short_description = 'Posts'

@admin.register(BlogTag)
class BlogTagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'post_count']
    prepopulated_fields = {'slug': ['name']}
    search_fields = ['name']
    
    def post_count(self, obj):
        return obj.posts.filter(is_published=True).count()
    post_count.short_description = 'Posts'

@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'author', 'is_published', 'is_featured', 'views', 'image_preview']
    list_filter = ['is_published', 'is_featured', 'category', 'created_at']
    search_fields = ['title', 'content', 'excerpt']
    prepopulated_fields = {'slug': ['title']}
    readonly_fields = ['views', 'likes', 'shares', 'reading_time', 'created_at', 'updated_at']
    filter_horizontal = ['tags', 'related_posts']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'excerpt', 'content', 'category', 'author')
        }),
        ('Media', {
            'fields': ('featured_image', 'thumbnail_image', 'gallery_images', 'video_url'),
            'classes': ('wide',)
        }),
        ('SEO & Metadata', {
            'fields': ('meta_title', 'meta_description', 'meta_keywords'),
            'classes': ('collapse',)
        }),
        ('Taxonomy', {
            'fields': ('tags', 'related_posts'),
            'classes': ('collapse',)
        }),
        ('Publication', {
            'fields': ('is_published', 'is_featured', 'published_at')
        }),
        ('Advanced', {
            'fields': ('layout_style', 'custom_css', 'schema_markup'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('views', 'likes', 'shares', 'reading_time'),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        if obj.featured_image:
            return format_html('<img src="{}" width="100" height="60" style="object-fit: cover; border-radius: 4px;" />', obj.featured_image.url)
        return "No Image"
    image_preview.short_description = 'Preview'

@admin.register(BlogComment)
class BlogCommentAdmin(admin.ModelAdmin):
    list_display = ['user', 'post', 'comment_preview', 'is_approved', 'created_at']
    list_filter = ['is_approved', 'created_at']
    search_fields = ['user__username', 'comment']
    actions = ['approve_comments', 'reject_comments']
    
    def comment_preview(self, obj):
        return obj.comment[:50] + '...' if len(obj.comment) > 50 else obj.comment
    comment_preview.short_description = 'Comment'
    
    def approve_comments(self, request, queryset):
        queryset.update(is_approved=True)
        self.message_user(request, f"{queryset.count()} comments approved.")
    approve_comments.short_description = "Approve selected comments"
    
    def reject_comments(self, request, queryset):
        queryset.update(is_approved=False)
        self.message_user(request, f"{queryset.count()} comments rejected.")
    reject_comments.short_description = "Reject selected comments"

@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ['email', 'name', 'is_active', 'created_at', 'status_badge']
    list_filter = ['is_active', 'created_at']
    search_fields = ['email', 'name']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['activate_subscribers', 'deactivate_subscribers', 'export_subscribers']
    
    fieldsets = (
        ('Subscriber Information', {
            'fields': ('email', 'name', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="background: #10b981; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">Active</span>')
        else:
            return format_html('<span style="background: #ef4444; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">Inactive</span>')
    status_badge.short_description = 'Status'
    
    def activate_subscribers(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} subscribers activated.")
    activate_subscribers.short_description = "Activate selected subscribers"
    
    def deactivate_subscribers(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} subscribers deactivated.")
    deactivate_subscribers.short_description = "Deactivate selected subscribers"
    
    def export_subscribers(self, request, queryset):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="newsletter_subscribers.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Email', 'Name', 'Status', 'Subscribe Date'])
        
        for subscriber in queryset:
            writer.writerow([
                subscriber.email,
                subscriber.name,
                'Active' if subscriber.is_active else 'Inactive',
                subscriber.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        
        return response
    export_subscribers.short_description = "Export selected subscribers"
    
    def get_queryset(self, request):
        return super().get_queryset(request).order_by('-created_at')
