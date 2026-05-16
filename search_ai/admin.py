from django.contrib import admin
from .models import SearchHistory, SearchAnalytics

@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ['query', 'user', 'results_count', 'created_at']
    list_filter = ['created_at']
    search_fields = ['query']
    readonly_fields = ['query', 'user', 'session_id', 'results_count', 'ip_address', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SearchAnalytics)
class SearchAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['query', 'product', 'clicked', 'position', 'created_at']
    list_filter = ['clicked', 'created_at']
    search_fields = ['query', 'product__name']
    readonly_fields = ['query', 'product', 'position', 'clicked', 'session_id', 'user', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
