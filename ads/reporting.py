from django.db.models import Count, Sum
from django.db.models.functions import Coalesce

from .models import AdAttribution, AdEvent


class AdvertiserReportingService:
    """Aggregate-only reporting boundary for advertiser-facing metrics."""

    def campaign_summary(self, advertiser_identity):
        events = AdEvent.objects.filter(advertiser_identity=advertiser_identity)
        attributions = AdAttribution.objects.filter(advertiser_identity=advertiser_identity)
        valid_attributions = attributions.exclude(
            lifecycle_status=AdAttribution.LIFECYCLE_REVERSED
        )
        impressions = events.filter(event_type=AdEvent.EVENT_IMPRESSION, metadata__internal_test__isnull=True).count()
        clicks = events.filter(event_type=AdEvent.EVENT_CLICK, metadata__internal_test__isnull=True).count()
        orders = valid_attributions.filter(order_item__isnull=False, metadata__internal_test__isnull=True).count()
        leads = valid_attributions.filter(metadata__commerce_event="qualified_service_lead", metadata__internal_test__isnull=True).count()
        revenue = (
            valid_attributions
            .filter(
                order_item__isnull=False,
                metadata__internal_test__isnull=True,
            )
            .aggregate(total=Sum(Coalesce("net_revenue_amount", "revenue_amount")))
            .get("total")
            or 0
        )

        return {
            "impressions": impressions,
            "clicks": clicks,
            "ctr": (clicks / impressions) if impressions else 0,
            "qualified_leads": leads,
            "orders": orders,
            "attributed_revenue": revenue,
            "campaigns": events.values("campaign_id").distinct().aggregate(count=Count("campaign_id"))["count"],
        }


advertiser_reporting_service = AdvertiserReportingService()
