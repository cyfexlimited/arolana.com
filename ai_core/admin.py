from django.contrib import admin

from .models import (
    AIAuditLog,
    AIDataBoundaryRule,
    AIModelConfig,
    AIProviderConfig,
    AIPromptTemplate,
    AIQuota,
    AIToolDefinition,
    AIUsageEvent,
)


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "is_active", "api_key_env_var", "updated_at")
    list_filter = ("provider", "is_active")
    search_fields = ("name", "api_key_env_var")


@admin.register(AIModelConfig)
class AIModelConfigAdmin(admin.ModelAdmin):
    list_display = ("feature", "model_name", "provider", "is_default", "supports_structured_outputs")
    list_filter = ("feature", "is_default", "supports_structured_outputs", "supports_tool_calls")
    search_fields = ("feature", "model_name")


@admin.register(AIPromptTemplate)
class AIPromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "version", "feature", "status", "approved_by", "approved_at", "updated_at")
    list_filter = ("feature", "status", "approved_at")
    search_fields = ("key", "title", "system_prompt", "developer_prompt")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AIToolDefinition)
class AIToolDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "feature", "is_active", "requires_human_approval", "safe_serializer")
    list_filter = ("feature", "is_active", "requires_human_approval")
    search_fields = ("name", "description", "safe_serializer")


@admin.register(AIDataBoundaryRule)
class AIDataBoundaryRuleAdmin(admin.ModelAdmin):
    list_display = ("model_label", "field_name", "action", "is_active", "updated_at")
    list_filter = ("action", "is_active", "model_label")
    search_fields = ("label", "model_label", "field_name", "reason")


@admin.register(AIQuota)
class AIQuotaAdmin(admin.ModelAdmin):
    list_display = ("role", "feature", "max_requests_per_day", "max_tokens_per_day", "max_cost_per_day", "is_active")
    list_filter = ("role", "feature", "is_active")
    search_fields = ("role", "feature")


@admin.register(AIUsageEvent)
class AIUsageEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "feature", "role", "provider", "model_name", "status", "input_tokens", "output_tokens", "estimated_cost")
    list_filter = ("feature", "role", "provider", "status", "created_at")
    search_fields = ("request_id", "session_key", "prompt_key", "model_name")
    readonly_fields = tuple(field.name for field in AIUsageEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AIAuditLog)
class AIAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "feature", "role", "object_label", "request_id")
    list_filter = ("action", "feature", "role", "created_at")
    search_fields = ("request_id", "safe_summary", "object_label", "object_id")
    readonly_fields = tuple(field.name for field in AIAuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
