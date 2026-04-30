from django.contrib import admin
from django.utils.html import format_html
from .models import FooterMenuCategory, FooterMenuItem

class FooterMenuItemInline(admin.TabularInline):
    model = FooterMenuItem
    extra = 1
    fields = ['title', 'url', 'display_order', 'is_external', 'open_in_new_tab', 'is_active']
    ordering = ['display_order']

@admin.register(FooterMenuCategory)
class FooterMenuCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'display_order', 'item_count', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}
    inlines = [FooterMenuItemInline]
    
    def item_count(self, obj):
        return obj.items.filter(is_active=True).count()
    item_count.short_description = 'Active Items'

@admin.register(FooterMenuItem)
class FooterMenuItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'url', 'display_order', 'is_active', 'open_in_new_tab']
    list_editable = ['display_order', 'is_active', 'open_in_new_tab']
    list_filter = ['category', 'is_active', 'is_external']
    search_fields = ['title', 'url']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('category', 'title', 'url', 'display_order')
        }),
        ('Options', {
            'fields': ('is_active', 'is_external', 'open_in_new_tab')
        }),
    )
