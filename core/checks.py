from django.conf import settings
from django.core.checks import Error, Tags, register

from core.private_upload_audit import audit_private_upload_security


@register(Tags.security)
def private_upload_security_check(app_configs, **kwargs):
    report = audit_private_upload_security(
        strict_all_fields=getattr(
            settings,
            "PRIVATE_UPLOAD_AUDIT_STRICT_ALL_FIELDS",
            False,
        )
    )
    messages = []

    for finding in report.errors:
        messages.append(
            Error(
                f"{finding.message} [{finding.identity}]",
                hint=finding.hint or None,
                id=finding.code,
            )
        )

    return messages
