from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse

from .models import (
    AIDataBoundaryRule,
    AIModelConfig,
    AIProviderConfig,
    AIPromptTemplate,
    AIQuota,
    AIToolDefinition,
)


@staff_member_required
def ai_core_status_api(request):
    return JsonResponse({
        "success": True,
        "providers": AIProviderConfig.objects.filter(is_active=True).count(),
        "models": AIModelConfig.objects.count(),
        "active_prompts": AIPromptTemplate.objects.filter(status=AIPromptTemplate.STATUS_ACTIVE).count(),
        "active_tools": AIToolDefinition.objects.filter(is_active=True).count(),
        "boundary_rules": AIDataBoundaryRule.objects.filter(is_active=True).count(),
        "active_quotas": AIQuota.objects.filter(is_active=True).count(),
    })
