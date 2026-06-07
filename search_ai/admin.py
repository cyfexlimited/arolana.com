from django.contrib import admin

from .models import SearchAnalytics, SearchHistory, VoiceSearchLog


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ['query', 'intent', 'category', 'results_count', 'ip_address', 'created_at']
    list_filter = ['intent', 'category', 'created_at']
    search_fields = ['query', 'category', 'session_id', 'ip_address']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SearchAnalytics)
class SearchAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['query', 'product', 'position', 'score', 'clicked', 'created_at']
    list_filter = ['clicked', 'created_at']
    search_fields = ['query', 'product__name', 'session_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(VoiceSearchLog)
class VoiceSearchLogAdmin(admin.ModelAdmin):
    list_display = ['transcript', 'results_count', 'ip_address', 'created_at']
    search_fields = ['transcript', 'ai_reply', 'session_id', 'ip_address']
    readonly_fields = ['created_at', 'updated_at']
