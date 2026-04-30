from django.contrib import admin
from .models import AdminActivityLog, SystemAlert

@admin.register(AdminActivityLog)
class AdminActivityLogAdmin(admin.ModelAdmin):
    list_display = ['admin', 'action_type', 'model_name', 'created_at']
    list_filter = ['action_type', 'model_name']
    search_fields = ['admin__username', 'object_repr']
    readonly_fields = ['admin', 'action_type', 'model_name', 'object_id', 'object_repr', 'changes', 'ip_address', 'user_agent', 'created_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False

@admin.register(SystemAlert)
class SystemAlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'level', 'is_read', 'is_dismissed', 'created_at']
    list_filter = ['level', 'is_read', 'is_dismissed']
    search_fields = ['title', 'message']
    list_editable = ['is_read', 'is_dismissed']
    
    fieldsets = (
        ('Alert Information', {
            'fields': ('title', 'message', 'level')
        }),
        ('Status', {
            'fields': ('is_read', 'is_dismissed', 'link')
        }),
    )
