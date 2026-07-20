from decimal import Decimal
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from .models import AIQuota, AIUsageEvent


def quota_for(role, feature):
    return AIQuota.objects.filter(role=role, feature=feature, is_active=True).first()


def assert_quota_available(role, feature, *, user=None, estimated_tokens=0, estimated_cost=Decimal("0.0000")):
    quota = quota_for(role, feature)
    if quota is None:
        return True

    since = timezone.now() - timedelta(days=1)
    usage = AIUsageEvent.objects.filter(role=role, feature=feature, created_at__gte=since)
    if user is not None:
        usage = usage.filter(user=user)

    request_count = usage.count()
    token_totals = usage.aggregate(
        input_total=Sum("input_tokens"),
        output_total=Sum("output_tokens"),
    )
    token_count = int(token_totals.get("input_total") or 0) + int(token_totals.get("output_total") or 0)
    cost_total = usage.aggregate(total=Sum("estimated_cost")).get("total") or Decimal("0.000000")

    if request_count >= quota.max_requests_per_day:
        raise PermissionError("AI daily request quota exceeded.")
    if int(token_count or 0) + int(estimated_tokens or 0) > quota.max_tokens_per_day:
        raise PermissionError("AI daily token quota exceeded.")
    if quota.max_cost_per_day and Decimal(str(cost_total)) + Decimal(str(estimated_cost or 0)) > quota.max_cost_per_day:
        raise PermissionError("AI daily cost quota exceeded.")
    return True
