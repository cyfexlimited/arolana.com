from django.contrib import admin
from .models import LoginReport, LoginAlert

@admin.register(LoginReport)
class LoginReportAdmin(admin.ModelAdmin):
    list_display = ['id', 'report_type', 'start_date', 'end_date', 'total_logins', 'successful_logins', 'failed_logins', 'generated_at']
    list_filter = ['report_type', 'generated_at']
    search_fields = ['report_type']
    readonly_fields = ['report_data', 'generated_at']
    
    fieldsets = (
        ('Report Information', {
            'fields': ('report_type', 'start_date', 'end_date')
        }),
        ('Statistics', {
            'fields': ('total_logins', 'successful_logins', 'failed_logins', 'unique_users', 'unique_ips')
        }),
        ('Data', {
            'fields': ('report_data', 'generated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(LoginAlert)
class LoginAlertAdmin(admin.ModelAdmin):
    list_display = ['alert_type', 'severity', 'ip_address', 'email', 'attempt_count', 'is_resolved', 'created_at']
    list_filter = ['alert_type', 'severity', 'is_resolved', 'created_at']
    search_fields = ['ip_address', 'email', 'notes']
    readonly_fields = ['created_at', 'resolved_at']
    
    fieldsets = (
        ('Alert Details', {
            'fields': ('alert_type', 'severity', 'ip_address', 'email', 'attempt_count')
        }),
        ('Resolution', {
            'fields': ('is_resolved', 'resolved_at', 'resolved_by', 'notes')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_resolved', 'mark_as_high_severity']
    
    def mark_as_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.update(is_resolved=True, resolved_at=timezone.now(), resolved_by=request.user)
        self.message_user(request, f"{queryset.count()} alert(s) marked as resolved.")
    mark_as_resolved.short_description = "Mark selected alerts as resolved"
    
    def mark_as_high_severity(self, request, queryset):
        queryset.update(severity='high')
        self.message_user(request, f"{queryset.count()} alert(s) marked as high severity.")
    mark_as_high_severity.short_description = "Mark as high severity"
