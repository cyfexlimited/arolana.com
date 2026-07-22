from dataclasses import dataclass
import signal
import time
import uuid

from .feature_flags import require_tool_execution_enabled
from .models import AIAuditLog, AIUsageEvent
from .permissions import require_role
from .registry import active_tool
from .schema_validation import SchemaValidationError, validate_schema, validate_source_references
from .tool_contracts import TOOL_CONTRACTS, TOOL_QUOTES_CREATE_QUOTE_REQUEST


QUOTE_CREATE_TOOL = TOOL_QUOTES_CREATE_QUOTE_REQUEST


class AIToolExecutionError(RuntimeError):
    pass


class AIToolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AIToolExecutionResult:
    tool_name: str
    created: bool
    payload: dict
    tool_call_id: str = ""
    status: str = "success"
    fallback_reason: str = ""


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


def _validate_payload_schema(contract, payload):
    try:
        return validate_schema(payload, contract.get("input_schema"), path="tool input")
    except SchemaValidationError as exc:
        raise AIToolValidationError(str(exc)) from None


class _Timeout:
    def __init__(self, seconds):
        self.seconds = int(seconds or 0)
        self.previous = None

    def __enter__(self):
        if self.seconds <= 0:
            return self
        self.previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._raise)
        signal.alarm(self.seconds)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.seconds > 0:
            signal.alarm(0)
            if self.previous is not None:
                signal.signal(signal.SIGALRM, self.previous)
        return False

    def _raise(self, signum, frame):
        raise TimeoutError("AI tool execution timed out.")


def _usage_event(*, context, contract, status, latency_ms, tool_call_id, fallback_reason=""):
    return AIUsageEvent.objects.create(
        user=context.get("user"),
        role=context.get("role", ""),
        feature=contract.get("feature", ""),
        provider="first_party_tool",
        model_name="deterministic",
        prompt_key=contract["name"],
        status=status,
        latency_ms=latency_ms,
        request_id=context.get("request_id", ""),
        session_key=context.get("session_key", ""),
        metadata={
            "tool_call_id": tool_call_id,
            "conversation_id": str(context.get("conversation_id", "")),
            "application_source": context.get("application_source", ""),
            "fallback_reason": fallback_reason,
        },
    )


def _audit_event(*, context, contract, action_status, tool_call_id, safe_summary, metadata=None):
    AIAuditLog.objects.create(
        user=context.get("user"),
        role=context.get("role", ""),
        feature=contract.get("feature", ""),
        action="tool_call",
        object_label=contract["name"],
        request_id=context.get("request_id", ""),
        safe_summary=safe_summary[:1000],
        metadata={
            "tool_call_id": tool_call_id,
            "conversation_id": str(context.get("conversation_id", "")),
            "status": action_status,
            **(metadata or {}),
        },
    )


def ensure_default_tool_definitions():
    from .models import AIToolDefinition

    for contract in TOOL_CONTRACTS.values():
        AIToolDefinition.objects.update_or_create(
            name=contract["name"],
            defaults={
                "feature": contract["feature"],
                "description": contract["description"],
                "input_schema": contract["input_schema"],
                "output_schema": contract["output_schema"],
                "allowed_roles": contract["allowed_roles"],
                "is_active": True,
                "requires_human_approval": contract["name"] == QUOTE_CREATE_TOOL,
                "safe_serializer": "ai_core.commerce_tools",
            },
        )


def execute_ai_tool(tool_name, payload, *, context=None):
    """
    Canonical first-party AI tool execution service.

    SmartChat and future callers must use this service rather than importing
    commerce handlers directly.
    """
    from .commerce_tools import TOOL_HANDLERS

    context = dict(context or {})
    role = context.get("role", "")
    tool_call_id = context.get("tool_call_id") or str(uuid.uuid4())
    started = time.monotonic()
    contract = TOOL_CONTRACTS.get(tool_name)
    if not contract:
        raise AIToolExecutionError(f"Unknown AI tool: {tool_name}")

    try:
        require_tool_execution_enabled()
        require_role(role, contract["allowed_roles"])
        active_tool(tool_name, role=role)
        _validate_payload_schema(contract, payload)

        if not contract.get("read_only", True) and tool_name != QUOTE_CREATE_TOOL:
            raise PermissionError("AI tools may not modify marketplace state.")

        with _Timeout(contract.get("timeout_seconds")):
            result = TOOL_HANDLERS[tool_name](payload or {}, {**context, "tool_call_id": tool_call_id})
        try:
            validate_schema(result, contract.get("output_schema"), path="tool output")
            validate_source_references(result, path="tool output")
        except SchemaValidationError as exc:
            raise AIToolValidationError("Tool output failed its public contract.") from None

        latency_ms = int((time.monotonic() - started) * 1000)
        _usage_event(
            context=context,
            contract=contract,
            status=AIUsageEvent.STATUS_SUCCESS,
            latency_ms=latency_ms,
            tool_call_id=tool_call_id,
        )
        _audit_event(
            context=context,
            contract=contract,
            action_status="success",
            tool_call_id=tool_call_id,
            safe_summary=f"{tool_name} executed successfully.",
        )
        return AIToolExecutionResult(
            tool_name=tool_name,
            created=bool(result.get("created")) if isinstance(result, dict) else False,
            payload=result or {},
            tool_call_id=tool_call_id,
            status="success",
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        fallback_reason = exc.__class__.__name__
        _usage_event(
            context=context,
            contract=contract,
            status=AIUsageEvent.STATUS_BLOCKED if isinstance(exc, (PermissionError, AIToolValidationError)) else AIUsageEvent.STATUS_ERROR,
            latency_ms=latency_ms,
            tool_call_id=tool_call_id,
            fallback_reason=fallback_reason,
        )
        _audit_event(
            context=context,
            contract=contract,
            action_status="error",
            tool_call_id=tool_call_id,
            safe_summary=f"{tool_name} failed safely: {fallback_reason}.",
            metadata={"error": fallback_reason},
        )
        raise
