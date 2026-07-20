from dataclasses import dataclass

from .feature_flags import require_tool_execution_enabled
from .registry import active_tool


QUOTE_CREATE_TOOL = "quotes.create_quote_request"


class AIToolExecutionError(RuntimeError):
    pass


class AIToolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AIToolExecutionResult:
    tool_name: str
    created: bool
    payload: dict


def validate_quote_request_payload(payload, *, user=None):
    """
    Enforce the safe draft quote-request contract before any write is attempted.
    """
    payload = payload or {}

    if not payload.get("customer_consent"):
        raise AIToolValidationError("Explicit customer consent is required.")

    requirements = payload.get("requirements") or {}
    if not isinstance(requirements, dict):
        raise AIToolValidationError("Captured requirements must be structured.")

    summary = str(requirements.get("summary") or payload.get("requirements_summary") or "").strip()
    if len(summary) < 20:
        raise AIToolValidationError("Sufficient captured requirements are required.")

    has_authenticated_user = user is not None and getattr(user, "is_authenticated", False)
    has_approved_guest_contact = bool(payload.get("approved_guest_contact"))
    if not has_authenticated_user and not has_approved_guest_contact:
        raise AIToolValidationError(
            "An authenticated user or approved guest-contact workflow is required."
        )

    if not str(payload.get("conversation_id") or payload.get("request_id") or "").strip():
        raise AIToolValidationError("A conversation/request id is required.")

    if not str(payload.get("idempotency_key") or "").strip():
        raise AIToolValidationError("An idempotency key is required.")

    return True


def execute_registered_tool(
    tool_name,
    payload,
    *,
    role,
    user=None,
    read_only=True,
    handler=None,
    duplicate_lookup=None,
):
    """
    Execute a registered AI tool with passive-safe defaults.

    Tool execution is disabled unless AI_CORE_ENABLED and
    AI_TOOL_EXECUTION_ENABLED are both true. All tools are read-only except the
    controlled draft quote-request creation tool.
    """
    require_tool_execution_enabled()
    tool = active_tool(tool_name, role=role)

    if not read_only and tool.name != QUOTE_CREATE_TOOL:
        raise PermissionError("AI tools may not modify marketplace state.")

    if tool.name == QUOTE_CREATE_TOOL:
        validate_quote_request_payload(payload, user=user)
        if duplicate_lookup is None:
            raise AIToolValidationError("Duplicate-request protection is required.")

        existing = duplicate_lookup(payload)
        if existing:
            return AIToolExecutionResult(tool_name=tool.name, created=False, payload=existing)

    if handler is None:
        raise AIToolExecutionError("No tool handler is configured.")

    result = handler(payload)
    return AIToolExecutionResult(tool_name=tool.name, created=not read_only, payload=result or {})

