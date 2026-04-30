from django.contrib import admin
from django.utils.html import format_html
from .models import SupportTopic, FAQ, HelpCenterHero, SupportArticle, CareerCategory, JobPosition, JobApplication, Page

@admin.register(SupportTopic)
class SupportTopicAdmin(admin.ModelAdmin):
    list_display = ['title', 'order', 'icon_preview', 'image_preview', 'is_active']
    list_editable = ['order', 'is_active']
    prepopulated_fields = {'slug': ['title']}
    
    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<i class="{} fa-2x"></i>', obj.icon)
        return "-"
    icon_preview.short_description = 'Icon'
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 8px;" />', obj.image.url)
        return "-"
    image_preview.short_description = 'Image'

@admin.register(CareerCategory)
class CareerCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order', 'is_active']
    prepopulated_fields = {'slug': ['name']}
    list_editable = ['order', 'is_active']

@admin.register(JobPosition)
class JobPositionAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'job_type', 'location', 'is_featured', 'is_active', 'is_open_status']
    list_filter = ['category', 'job_type', 'experience_level', 'is_featured', 'is_active']
    search_fields = ['title', 'description', 'requirements']
    prepopulated_fields = {'slug': ['title']}
    list_editable = ['is_featured', 'is_active']
    readonly_fields = ['publish_date']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'category', 'job_type', 'experience_level')
        }),
        ('Location & Compensation', {
            'fields': ('location', 'salary_range')
        }),
        ('Job Description', {
            'fields': ('description', 'responsibilities', 'requirements', 'benefits')
        }),
        ('Application Settings', {
            'fields': ('application_email', 'application_url')
        }),
        ('Publishing', {
            'fields': ('is_featured', 'is_active', 'closing_date'),
            'description': 'publish_date is set automatically when created'
        }),
    )
    
    def is_open_status(self, obj):
        return obj.is_open()
    is_open_status.boolean = True
    is_open_status.short_description = 'Open'

@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'position', 'email', 'status', 'created_at']
    list_filter = ['status', 'position']
    search_fields = ['first_name', 'last_name', 'email']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Applicant Information', {
            'fields': ('first_name', 'last_name', 'email', 'phone')
        }),
        ('Application Details', {
            'fields': ('position', 'cover_letter', 'resume', 'portfolio_url', 'linkedin_url')
        }),
        ('Review Status', {
            'fields': ('status', 'notes')
        }),
    )

@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ['question', 'category', 'order', 'is_featured', 'is_active', 'image_preview']
    list_filter = ['category', 'is_featured', 'is_active']
    search_fields = ['question', 'answer']
    list_editable = ['order', 'is_featured', 'is_active']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="40" height="40" style="border-radius: 4px;" />', obj.image.url)
        return "-"
    image_preview.short_description = 'Image'

@admin.register(HelpCenterHero)
class HelpCenterHeroAdmin(admin.ModelAdmin):
    list_display = ['title', 'is_active', 'image_preview']
    
    def image_preview(self, obj):
        if obj.background_image:
            return format_html('<img src="{}" width="100" height="50" style="border-radius: 4px;" />', obj.background_image.url)
        return "-"
    image_preview.short_description = 'Background'

@admin.register(SupportArticle)
class SupportArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'views', 'helpful_count', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['title', 'content']
    prepopulated_fields = {'slug': ['title']}
    readonly_fields = ['views', 'helpful_count', 'not_helpful_count']

@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'is_active', 'show_in_footer', 'show_in_header', 'updated_at']
    list_filter = ['is_active', 'show_in_footer', 'show_in_header']
    search_fields = ['title', 'content']
    prepopulated_fields = {'slug': ['title']}
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'content', 'is_active')
        }),
        ('SEO', {
            'fields': ('meta_description', 'meta_keywords'),
            'classes': ('collapse',)
        }),
        ('Display Options', {
            'fields': ('show_in_footer', 'show_in_header', 'footer_order'),
            'classes': ('collapse',)
        }),
        ('Sidebar', {
            'fields': ('sidebar_content',),
            'classes': ('collapse',)
        }),
    )
