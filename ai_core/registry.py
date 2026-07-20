from .models import AIPromptTemplate, AIToolDefinition
from .permissions import require_role


def active_prompt(key, role=None):
    prompt = (
        AIPromptTemplate.objects
        .filter(key=key, status=AIPromptTemplate.STATUS_ACTIVE)
        .order_by("-version")
        .first()
    )
    if prompt is None:
        raise LookupError(f"No active AI prompt registered for {key}.")
    if role:
        require_role(role, prompt.allowed_roles or ["admin"])
    return prompt


def active_tool(name, role=None):
    tool = AIToolDefinition.objects.filter(name=name, is_active=True).first()
    if tool is None:
        raise LookupError(f"No active AI tool registered for {name}.")
    if role:
        require_role(role, tool.allowed_roles or ["admin"])
    return tool
